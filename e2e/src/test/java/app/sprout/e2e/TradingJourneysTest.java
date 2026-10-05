package app.sprout.e2e;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Trading, through the gateway, against the real exchange and the simulated market: a customer
 * funded the Phase 2 way (a deposit approved in Sprout Bank with their UPI PIN) buys and sells.
 * Prices move while the tests run, so they check the books by identities (what was paid, what is
 * held) rather than by fixed numbers.
 */
class TradingJourneysTest {

    static final String OMS = "/api/oms";
    static final BigDecimal DEPOSIT = new BigDecimal("50000.00");
    final Client c = new Client();
    String token;

    @BeforeEach
    void fundedCustomerInTheTradingDay() throws InterruptedException {
        token = Customers.funded(c, DEPOSIT);
        Customers.waitForTradingWindow(c);
    }

    // ── helpers ──────────────────────────────────────────────────────────────

    Client.Response place(String key, Map<String, Object> order) {
        return c.send("POST", OMS + "/v1/orders", order, Map.of("Authorization", "Bearer " + token, "Idempotency-Key", key));
    }

    JsonNode order(String symbol, String side, int qty, String type, String limit, String product) {
        Map<String, Object> o = new LinkedHashMap<>();
        o.put("symbol", symbol);
        o.put("side", side);
        o.put("quantity", qty);
        o.put("orderType", type);
        if (limit != null) {
            o.put("limitPrice", limit);
        }
        o.put("product", product);
        Client.Response r = place(UUID.randomUUID().toString(), o);
        assertThat(r.status()).as(r.body().toString()).isEqualTo(201);
        return r.body();
    }

    JsonNode filled(String symbol, String side, int qty, String product) {
        JsonNode o = order(symbol, side, qty, "MARKET", null, product);
        assertThat(o.path("status").asText()).as(o.toString()).isEqualTo("FILLED");
        return o;
    }

    BigDecimal money(String field) {
        return new BigDecimal(c.get(OMS + "/v1/funds", token).body().path(field).asText());
    }

    static BigDecimal amount(JsonNode node) {
        return new BigDecimal(node.asText());
    }

    JsonNode quote(String symbol) {
        return c.get("/api/marketdata/v1/quotes?symbols=" + symbol, token).body().path("quotes").get(0);
    }

    /** A price on the tick, this fraction of the previous close: inside the band, far from the market. */
    String priceAt(String symbol, String fraction) {
        BigDecimal prev = BigDecimal.valueOf(quote(symbol).path("prevClose").asDouble());
        BigDecimal p = prev.multiply(new BigDecimal(fraction)).divide(new BigDecimal("0.05"), 0, RoundingMode.CEILING)
                .multiply(new BigDecimal("0.05"));
        return p.setScale(2, RoundingMode.UNNECESSARY).toPlainString();
    }

    JsonNode holding(String symbol) {
        for (JsonNode h : c.get(OMS + "/v1/holdings", token).body().path("holdings")) {
            if (h.path("symbol").asText().equals(symbol)) {
                return h;
            }
        }
        return null;
    }

    JsonNode position(String symbol) {
        for (JsonNode p : c.get(OMS + "/v1/positions", token).body().path("positions")) {
            if (p.path("symbol").asText().equals(symbol)) {
                return p;
            }
        }
        return null;
    }

    // ── delivery ─────────────────────────────────────────────────────────────

    @Test
    @DisplayName("E2E-60 buy for delivery at the market: executed on the exchange, paid with its charges, held as T1 shares")
    void deliveryBuy() {
        JsonNode o = filled("HARBOR", "BUY", 3, "CNC");
        BigDecimal value = amount(o.path("value"));
        BigDecimal charges = amount(o.path("charges").path("total"));
        assertThat(value).isEqualByComparingTo(amount(o.path("price")).multiply(BigDecimal.valueOf(3)));
        assertThat(amount(o.path("charges").path("brokerage"))).isZero();
        assertThat(amount(o.path("charges").path("stt"))).isPositive();
        assertThat(money("cash")).isEqualByComparingTo(DEPOSIT.subtract(value).subtract(charges));
        assertThat(money("blocked")).isZero();
        JsonNode h = holding("HARBOR");
        assertThat(h.path("quantity").asInt()).isEqualTo(3);
        assertThat(h.path("t1Quantity").asInt()).isEqualTo(3);
        assertThat(amount(h.path("investedValue"))).isEqualByComparingTo(value);
    }

    @Test
    @DisplayName("E2E-61 sell only what you hold; the proceeds wait for settlement")
    void deliverySell() {
        filled("INKWELL", "BUY", 5, "CNC");
        JsonNode tooMany = order("INKWELL", "SELL", 6, "MARKET", null, "CNC");
        assertThat(tooMany.path("status").asText()).isEqualTo("REJECTED");
        assertThat(tooMany.path("rejection").path("code").asText()).isEqualTo("INSUFFICIENT_HOLDINGS");
        JsonNode sold = filled("INKWELL", "SELL", 2, "CNC");
        assertThat(money("unsettled")).isEqualByComparingTo(amount(sold.path("value")).subtract(amount(sold.path("charges").path("total"))));
        assertThat(sold.has("realisedPnl")).isTrue();
        assertThat(holding("INKWELL").path("quantity").asInt()).isEqualTo(3);
    }

    @Test
    @DisplayName("E2E-62 a limit order away from the market rests with its money blocked; cancelling gives back every paisa")
    void restingLimitAndCancel() {
        String low = priceAt("HARBOR", "0.85");
        JsonNode o = order("HARBOR", "BUY", 4, "LIMIT", low, "CNC");
        assertThat(o.path("status").asText()).isEqualTo("OPEN");
        BigDecimal blocked = amount(o.path("blocked"));
        assertThat(blocked).isGreaterThan(new BigDecimal(low).multiply(BigDecimal.valueOf(4)));
        assertThat(money("blocked")).isEqualByComparingTo(blocked);
        assertThat(money("cash")).isEqualByComparingTo(DEPOSIT.subtract(blocked));
        Client.Response cancelled = c.send("DELETE", OMS + "/v1/orders/" + o.path("id").asText(), null, Map.of("Authorization", "Bearer " + token));
        assertThat(cancelled.status()).isEqualTo(200);
        assertThat(cancelled.body().path("status").asText()).isEqualTo("CANCELLED");
        assertThat(money("cash")).isEqualByComparingTo(DEPOSIT);
        assertThat(money("blocked")).isZero();
    }

    @Test
    @DisplayName("E2E-63 an order beyond your money is rejected and blocks nothing")
    void insufficientFunds() {
        JsonNode o = order("HARBOR", "BUY", 5000, "MARKET", null, "CNC");
        assertThat(o.path("status").asText()).isEqualTo("REJECTED");
        assertThat(o.path("rejection").path("code").asText()).isEqualTo("INSUFFICIENT_FUNDS");
        assertThat(money("cash")).isEqualByComparingTo(DEPOSIT);
    }

    // ── intraday ─────────────────────────────────────────────────────────────

    @Test
    @DisplayName("E2E-64 intraday: a fifth as margin, a round trip books its profit or loss, and the books add up")
    void intradayRoundTrip() {
        JsonNode buy = filled("KOSHA", "BUY", 20, "MIS");
        BigDecimal buyValue = amount(buy.path("value"));
        JsonNode p = position("KOSHA");
        assertThat(p.path("quantity").asInt()).isEqualTo(20);
        assertThat(amount(p.path("margin"))).isEqualByComparingTo(buyValue.divide(BigDecimal.valueOf(5), 2, RoundingMode.CEILING));
        assertThat(money("blocked")).isEqualByComparingTo(amount(p.path("margin")));
        JsonNode sell = filled("KOSHA", "SELL", 20, "MIS");
        BigDecimal pnl = amount(sell.path("value")).subtract(buyValue);
        assertThat(amount(sell.path("realisedPnl"))).isEqualByComparingTo(pnl);
        assertThat(position("KOSHA").path("quantity").asInt()).isZero();
        assertThat(money("blocked")).isZero();
        BigDecimal charges = amount(buy.path("charges").path("total")).add(amount(sell.path("charges").path("total")));
        // whatever the market did: what the customer has is what they put in, plus the P&L, less the charges
        BigDecimal has = money("cash").add(money("unsettled")).subtract(money("dues"));
        assertThat(has).isEqualByComparingTo(DEPOSIT.add(pnl).subtract(charges));
    }

    @Test
    @DisplayName("E2E-65 intraday lets you sell first and buy back; delivery doesn't let you sell what you don't own")
    void intradayShort() {
        JsonNode shortSale = filled("HARBOR", "SELL", 10, "MIS");
        assertThat(position("HARBOR").path("quantity").asInt()).isEqualTo(-10);
        JsonNode flip = order("HARBOR", "BUY", 15, "MARKET", null, "MIS");
        assertThat(flip.path("rejection").path("code").asText()).isEqualTo("POSITION_FLIP");
        JsonNode cover = filled("HARBOR", "BUY", 10, "MIS");
        assertThat(amount(cover.path("realisedPnl"))).isEqualByComparingTo(amount(shortSale.path("value")).subtract(amount(cover.path("value"))));
        assertThat(order("HARBOR", "SELL", 1, "MARKET", null, "CNC").path("rejection").path("code").asText()).isEqualTo("INSUFFICIENT_HOLDINGS");
    }

    // ── the rules ────────────────────────────────────────────────────────────

    @Test
    @DisplayName("E2E-66 the exchange's rules: prices on the tick and inside the day's band; unknown shares are refused")
    void exchangeRules() {
        String odd = new BigDecimal(priceAt("HARBOR", "0.95")).add(new BigDecimal("0.02")).toPlainString();
        assertThat(order("HARBOR", "BUY", 1, "LIMIT", odd, "CNC").path("rejection").path("code").asText()).isEqualTo("INVALID_TICK");
        assertThat(order("HARBOR", "BUY", 1, "LIMIT", priceAt("HARBOR", "1.25"), "CNC").path("rejection").path("code").asText())
                .isEqualTo("PRICE_OUT_OF_BAND");
        Client.Response unknown = place(UUID.randomUUID().toString(), Map.of("symbol", "NOSUCH", "side", "BUY", "quantity", 1,
                "orderType", "MARKET", "product", "CNC"));
        assertThat(unknown.status()).isEqualTo(422);
        assertThat(unknown.code()).isEqualTo("UNKNOWN_INSTRUMENT");
        assertThat(money("cash")).isEqualByComparingTo(DEPOSIT);
    }

    @Test
    @DisplayName("E2E-67 retrying an order with the same Idempotency-Key places it once")
    void idempotentOrders() {
        String key = UUID.randomUUID().toString();
        Map<String, Object> o = Map.of("symbol", "INKWELL", "side", "BUY", "quantity", 2, "orderType", "MARKET", "product", "CNC");
        Client.Response first = place(key, o);
        Client.Response again = place(key, o);
        assertThat(first.status()).isEqualTo(201);
        assertThat(again.status()).isEqualTo(200);
        assertThat(again.body().path("id").asText()).isEqualTo(first.body().path("id").asText());
        assertThat(holding("INKWELL").path("quantity").asInt()).isEqualTo(2);
    }

    @Test
    @DisplayName("E2E-68 nobody else can see or cancel my orders")
    void strangers() {
        JsonNode o = order("HARBOR", "BUY", 1, "LIMIT", priceAt("HARBOR", "0.85"), "CNC");
        String stranger = new Client().account(Client.newEmail()).path("accessToken").asText();
        assertThat(c.get(OMS + "/v1/orders/" + o.path("id").asText(), stranger).status()).isEqualTo(404);
        assertThat(c.send("DELETE", OMS + "/v1/orders/" + o.path("id").asText(), null, Map.of("Authorization", "Bearer " + stranger))
                .status()).isEqualTo(404);
        assertThat(c.get(OMS + "/v1/orders/" + o.path("id").asText(), token).body().path("status").asText()).isEqualTo("OPEN");
        assertThat(c.get(OMS + "/v1/orders", null).status()).isEqualTo(401);
    }

    @Test
    @DisplayName("E2E-69 a forged execution report is refused")
    void forgedExecution() {
        JsonNode o = order("HARBOR", "BUY", 1, "LIMIT", priceAt("HARBOR", "0.85"), "CNC");
        Client.Response forged = c.send("POST", OMS + "/internal/v1/exchange-events",
                Map.of("eventId", UUID.randomUUID().toString(), "type", "ORDER_FILLED", "clientOrderId", o.path("id").asText(),
                        "exchangeOrderId", UUID.randomUUID().toString(), "symbol", "HARBOR", "side", "BUY", "quantity", 1,
                        "price", "1.00", "tradeId", UUID.randomUUID().toString(), "occurredAt", "2026-10-05T00:00:00Z"),
                Map.of("Authorization", "Bearer " + token, "X-Exchange-Signature", "sha256=" + "0".repeat(64)));
        assertThat(forged.code()).isEqualTo("INVALID_SIGNATURE");
        assertThat(c.get(OMS + "/v1/orders/" + o.path("id").asText(), token).body().path("status").asText()).isEqualTo("OPEN");
    }
}
