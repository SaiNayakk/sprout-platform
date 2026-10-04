package app.sprout.hosts.trading;

import app.sprout.hosts.common.HostLogFields.HostInfo;
import app.sprout.marketdata.MarketDataApplication;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.ConfigurableApplicationContext;

/**
 * The trading host: market data today; orders and risk join it as they're built, each in its own
 * Spring context, as in the edge host.
 *
 * <p>It is a separate JVM from the edge host on purpose: a fault here (a stuck market clock, a
 * flood of price streams, running out of memory) must not take sign-in down with it. CHAOS-03
 * tests exactly that.
 */
public final class TradingHost {

    private static final Logger log = LoggerFactory.getLogger(TradingHost.class);

    private TradingHost() {}

    public static void main(String[] args) {
        try {
            start(args);
        } catch (RuntimeException e) {
            log.error("The trading host couldn't start; exiting so it gets restarted", e);
            System.exit(1);
        }
    }

    public static ConfigurableApplicationContext[] start(String... args) {
        HostInfo host = HostInfo.load();
        ConfigurableApplicationContext marketData = MarketDataApplication.builder()
                .properties(host.loggingDefaults())
                .run(args);
        log.info("Trading host up: market data running");
        return new ConfigurableApplicationContext[] {marketData};
    }
}
