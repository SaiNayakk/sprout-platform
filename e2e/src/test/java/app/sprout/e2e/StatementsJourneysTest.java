package app.sprout.e2e;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.ZoneId;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * A customer's records, through the gateway, after real trading: a delivery buy and an intraday round
 * trip. Statements are read from the books, so they must agree with what trading said at the time.
 */
class StatementsJourneysTest {

    static final BigDecimal DEPOSIT = new BigDecimal("40000.00");
    final Client c = new Client();
    String token;
    String session;
    JsonNode buy;
    JsonNode intradayBuy;
    JsonNode intradaySell;

    @BeforeEach
    void aCustomerWhoTradedToday() throws InterruptedException {
        token = Customers.funded(c, DEPOSIT);
        Customers.waitForTradingWindow(c);
        session = c.get("/api/marketdata/v1/market", null).body().path("sessionDate").asText();
        buy = filled("HARBOR", "BUY", 2, "CNC");
        intradayBuy = filled("KOSHA", "BUY", 10, "MIS");
        intradaySell = filled("KOSHA", "SELL", 10, "MIS");
    }

    JsonNode filled(String symbol, String side, int qty, String product) {
        Map<String, Object> o = new LinkedHashMap<>();
        o.put("symbol", symbol);
        o.put("side", side);
        o.put("quantity", qty);
        o.put("orderType", "MARKET");
        o.put("product", product);
        JsonNode r = c.send("POST", "/api/oms/v1/orders", o, Map.of("Authorization", "Bearer " + token, "Idempotency-Key",
                UUID.randomUUID().toString())).body();
        assertThat(r.path("status").asText()).as(r.toString()).isEqualTo("FILLED");
        return r;
    }

    static BigDecimal amount(JsonNode n) {
        return new BigDecimal(n.asText());
    }

    BigDecimal charges() {
        return amount(buy.path("charges").path("total")).add(amount(intradayBuy.path("charges").path("total")))
                .add(amount(intradaySell.path("charges").path("total")));
    }

    @Test
    @DisplayName("E2E-70 today's contract note lists every execution and charge, and adds up")
    void contractNote() {
        JsonNode list = c.get("/api/statements/v1/contract-notes", token).body().path("contractNotes");
        assertThat(list.size()).isEqualTo(1);
        assertThat(list.get(0).path("tradeDate").asText()).isEqualTo(session);
        JsonNode note = c.get("/api/statements/v1/contract-notes/" + session, token).body();
        assertThat(note.path("trades").size()).isEqualTo(3);
        assertThat(note.path("client").path("dematAccount").asText()).matches("[0-9]{16}");
        BigDecimal bought = amount(buy.path("value")).add(amount(intradayBuy.path("value")));
        BigDecimal sold = amount(intradaySell.path("value"));
        assertThat(amount(note.path("bought"))).isEqualByComparingTo(bought);
        assertThat(amount(note.path("sold"))).isEqualByComparingTo(sold);
        assertThat(amount(note.path("charges").path("total"))).isEqualByComparingTo(charges());
        assertThat(amount(note.path("net"))).isEqualByComparingTo(sold.subtract(bought).subtract(charges()));
    }

    @Test
    @DisplayName("E2E-71 the funds statement shows the deposit and every trade, and ends at the cash Sprout shows")
    void fundsStatement() {
        LocalDate today = LocalDate.now(ZoneId.of("Asia/Kolkata"));
        JsonNode st = c.get("/api/statements/v1/funds-statement?from=" + today.minusDays(1) + "&to=" + today.plusDays(1), token).body();
        assertThat(amount(st.path("openingBalance"))).isZero();
        assertThat(st.path("lines").get(0).path("credit").asText()).as("the deposit").isEqualTo(DEPOSIT.toPlainString());
        assertThat(st.path("lines").size()).as("deposit, then each execution's effect on cash").isGreaterThanOrEqualTo(4);
        BigDecimal cash = amount(c.get("/api/oms/v1/funds", token).body().path("cash"));
        assertThat(amount(st.path("closingBalance"))).isEqualByComparingTo(cash);
    }

    @Test
    @DisplayName("E2E-72 profit and loss puts the intraday round trip under intraday, with charges beside")
    void profitAndLoss() {
        LocalDate day = LocalDate.parse(session);
        JsonNode pnl = c.get("/api/statements/v1/pnl?from=" + day.minusDays(1) + "&to=" + day, token).body();
        assertThat(amount(pnl.path("intraday"))).isEqualByComparingTo(amount(intradaySell.path("realisedPnl")));
        assertThat(amount(pnl.path("shortTerm"))).isZero();
        assertThat(amount(pnl.path("charges"))).isEqualByComparingTo(charges());
        assertThat(pnl.path("lines").size()).isEqualTo(1);
    }

    @Test
    @DisplayName("E2E-73 the holdings statement is the depository's record: shares bought today aren't in it until they settle")
    void holdingsStatement() {
        JsonNode h = c.get("/api/statements/v1/holdings-statement", token).body();
        assertThat(h.path("dematAccount").asText()).matches("[0-9]{16}");
        assertThat(h.path("holdings").size()).as("T1: not delivered yet").isZero();
        assertThat(c.get("/api/oms/v1/holdings", token).body().path("holdings").get(0).path("t1Quantity").asInt()).isEqualTo(2);
    }

    @Test
    @DisplayName("E2E-74 statements are only for signed-in customers with an account")
    void strangers() {
        assertThat(c.get("/api/statements/v1/contract-notes", null).status()).isEqualTo(401);
        String noAccount = new Client().account(Client.newEmail()).path("accessToken").asText();
        Client.Response r = c.get("/api/statements/v1/contract-notes", noAccount);
        assertThat(r.status()).isEqualTo(404);
        assertThat(r.code()).isEqualTo("NO_ACCOUNT");
    }
}
