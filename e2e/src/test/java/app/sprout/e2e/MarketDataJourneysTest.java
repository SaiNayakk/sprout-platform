package app.sprout.e2e;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Market data through the gateway, as the app will use it. Written to pass at any moment of the
 * simulated day: the market may be open, closed or between sessions when a test runs.
 */
class MarketDataJourneysTest {

    static final String MD = "/api/marketdata";
    final Client c = new Client();
    String token;

    @BeforeEach
    void signIn() {
        token = c.account(Client.newEmail()).path("accessToken").asText();
    }

    JsonNode market() {
        return c.get(MD + "/v1/market", null).body();
    }

    // ── public reference data ────────────────────────────────────────────────

    @Test
    @DisplayName("E2E-40 the market and its instruments are visible before signing in")
    void publicReferenceData() {
        Client.Response market = c.get(MD + "/v1/market", null);
        assertThat(market.status()).isEqualTo(200);
        assertThat(market.body().path("mode").asText()).isEqualTo("SYNTHETIC");
        assertThat(market.body().path("source").asText()).contains("Not real prices");
        JsonNode instruments = c.get(MD + "/v1/instruments", null).body().path("instruments");
        assertThat(instruments.size()).isGreaterThanOrEqualTo(2);
        List<String> indices = new ArrayList<>();
        instruments.forEach(i -> {
            if (i.path("type").asText().equals("INDEX")) {
                indices.add(i.path("symbol").asText());
                assertThat(i.path("tradable").asBoolean()).as("an index can't be bought").isFalse();
            }
        });
        assertThat(indices).isNotEmpty();
        assertThat(c.get(MD + "/v1/instruments/" + instruments.get(0).path("symbol").asText(), null).status()).isEqualTo(200);
    }

    @Test
    @DisplayName("E2E-41 prices need a signed-in user")
    void pricesNeedSignIn() {
        assertThat(c.get(MD + "/v1/quotes?symbols=HARBOR", null).code()).isEqualTo("UNAUTHENTICATED");
        assertThat(c.get(MD + "/v1/candles/HARBOR?interval=1d", null).status()).isEqualTo(401);
    }

    // ── prices ───────────────────────────────────────────────────────────────

    @Test
    @DisplayName("E2E-42 quotes come back in the order asked; unknown symbols are named")
    void quotes() {
        Client.Response r = c.get(MD + "/v1/quotes?symbols=inkwell,HARBOR", token);
        assertThat(r.status()).isEqualTo(200);
        assertThat(r.body().path("quotes")).extracting(q -> q.path("symbol").asText()).containsExactly("INKWELL", "HARBOR");
        JsonNode q = r.body().path("quotes").get(0);
        assertThat(q.path("low").asDouble()).isLessThanOrEqualTo(q.path("last").asDouble());
        assertThat(q.path("high").asDouble()).isGreaterThanOrEqualTo(q.path("last").asDouble());

        Client.Response unknown = c.get(MD + "/v1/quotes?symbols=HARBOR,NOTREAL", token);
        assertThat(unknown.status()).isEqualTo(404);
        assertThat(unknown.code()).isEqualTo("UNKNOWN_INSTRUMENT");
        assertThat(unknown.body().path("detail").asText()).contains("NOTREAL");
    }

    @Test
    @DisplayName("E2E-43 candles never show the future")
    void candlesNeverShowTheFuture() {
        JsonNode m = market();
        OffsetDateTime now = OffsetDateTime.parse(m.path("marketTime").asText());
        JsonNode candles = c.get(MD + "/v1/candles/HARBOR?interval=1m", token).body().path("candles");
        int forming = 0;
        for (JsonNode candle : candles) {
            OffsetDateTime start = OffsetDateTime.parse(candle.path("ts").asText());
            if (candle.path("complete").asBoolean()) {
                assertThat(start.plusMinutes(1)).as("a complete candle has ended").isBeforeOrEqualTo(now.plusSeconds(2));
            } else {
                forming++;
            }
            assertThat(start).isBeforeOrEqualTo(now.plusSeconds(2));
        }
        assertThat(forming).isLessThanOrEqualTo(1);

        JsonNode daily = c.get(MD + "/v1/candles/HARBOR?interval=1d&limit=250", token).body().path("candles");
        assertThat(daily.size()).isGreaterThan(200);
        String last = daily.get(daily.size() - 1).path("ts").asText().substring(0, 10);
        assertThat(last).as("history ends at the session being shown").isLessThanOrEqualTo(m.path("sessionDate").asText());
    }

    // ── the live stream ──────────────────────────────────────────────────────

    @Test
    @DisplayName("E2E-44 the price stream starts with the current state, then ticks live with rising seq")
    void liveStream() throws Exception {
        waitForOpenMarket();
        try (EventStream s = EventStream.open("symbols=HARBOR,INKWELL", token, c.clientIp)) {
            assertThat(s.status).isEqualTo(200);
            List<EventStream.Event> ticks = s.await("tick", 40, Duration.ofSeconds(10));
            assertThat(ticks).hasSizeGreaterThanOrEqualTo(40);
            assertThat(s.events.get(0).name()).isEqualTo("market");
            assertThat(s.events.subList(1, 3)).extracting(EventStream.Event::name).containsOnly("quote");

            Map<String, Long> seq = new HashMap<>();
            s.named("quote").forEach(q -> seq.put(q.data().path("symbol").asText(), q.data().path("seq").asLong()));
            for (EventStream.Event t : ticks) {
                String sym = t.data().path("symbol").asText();
                long n = t.data().path("seq").asLong();
                assertThat(n).as(sym + " seq").isGreaterThan(seq.get(sym));
                seq.put(sym, n);
            }
            Duration spread = Duration.between(ticks.get(0).receivedAt(), ticks.get(ticks.size() - 1).receivedAt());
            assertThat(spread).as("ticks arrive over time, not in one batch").isGreaterThan(Duration.ofMillis(500));
        }
    }

    @Test
    @DisplayName("E2E-45 every streamed price lies inside its minute's high and low")
    void ticksAgreeWithCandles() throws Exception {
        waitForOpenMarket();
        List<EventStream.Event> ticks;
        try (EventStream s = EventStream.open("symbols=KOSHA", token, c.clientIp)) {
            ticks = s.await("tick", 60, Duration.ofSeconds(15));
        }
        Thread.sleep(3000); // let the minutes they belong to finish (30x speed: 2 s per minute)
        JsonNode candles = c.get(MD + "/v1/candles/KOSHA?interval=1m", token).body().path("candles");
        Map<String, JsonNode> byMinute = new HashMap<>();
        candles.forEach(cd -> byMinute.put(cd.path("ts").asText().substring(0, 16), cd));
        int checked = 0;
        for (EventStream.Event t : ticks) {
            JsonNode candle = byMinute.get(t.data().path("ts").asText().substring(0, 16));
            if (candle == null || !candle.path("complete").asBoolean()) {
                continue; // a minute from another session, or still forming
            }
            double p = t.data().path("price").asDouble();
            assertThat(p).as(t.data().toString()).isBetween(candle.path("low").asDouble(), candle.path("high").asDouble());
            checked++;
        }
        assertThat(checked).isGreaterThan(20);
    }

    @Test
    @DisplayName("E2E-46 one client can hold at most five price streams")
    void streamCap() throws Exception {
        List<EventStream> open = new ArrayList<>();
        try {
            for (int i = 0; i < 5; i++) {
                EventStream s = EventStream.open("symbols=HARBOR", token, c.clientIp);
                assertThat(s.status).isEqualTo(200);
                open.add(s);
            }
            EventStream sixth = EventStream.open("symbols=HARBOR", token, c.clientIp);
            assertThat(sixth.status).isEqualTo(429);
            assertThat(sixth.error.path("code").asText()).isEqualTo("RATE_LIMITED");
        } finally {
            for (EventStream s : open) {
                s.close();
            }
        }
    }

    @Test
    @DisplayName("E2E-47 a bad stream request is refused before it starts")
    void badStreamRequests() throws Exception {
        try (EventStream unknown = EventStream.open("symbols=HARBOR,NOTREAL", token, c.clientIp)) {
            assertThat(unknown.status).isEqualTo(404);
            assertThat(unknown.error.path("code").asText()).isEqualTo("UNKNOWN_INSTRUMENT");
        }
        StringBuilder many = new StringBuilder("symbols=");
        for (int i = 0; i < 51; i++) {
            many.append("S").append(i).append(',');
        }
        try (EventStream tooMany = EventStream.open(many.toString(), token, c.clientIp)) {
            assertThat(tooMany.status).isEqualTo(400);
        }
        try (EventStream anonymous = EventStream.open("symbols=HARBOR", null, c.clientIp)) {
            assertThat(anonymous.status).isEqualTo(401);
        }
    }

    /** The accelerated market spends some seconds closed between sessions; wait those out. */
    void waitForOpenMarket() throws InterruptedException {
        for (int i = 0; i < 60 && !market().path("state").asText().equals("OPEN"); i++) {
            Thread.sleep(500);
        }
        assertThat(market().path("state").asText()).isEqualTo("OPEN");
    }
}
