package app.sprout.hosts.trading;

import app.sprout.habits.HabitsApplication;
import app.sprout.hosts.common.HostLogFields.HostInfo;
import app.sprout.hosts.common.NoDatabase;
import app.sprout.marketdata.MarketDataApplication;
import app.sprout.oms.OmsApplication;
import app.sprout.plans.PlansApplication;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.ConfigurableApplicationContext;

/**
 * The trading host: market data, the order service with its risk checks, plans (SIPs) and habits,
 * each in its own Spring context, as in the edge host. Orders read prices on every placement and risk
 * round, and plans and habits work from orders, so they live together.
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
                .properties("spring.autoconfigure.exclude=" + NoDatabase.EXCLUDES)   // market data has no database
                .run(args);
        ConfigurableApplicationContext oms = OmsApplication.builder()
                .properties(host.loggingDefaults())
                .run(args);
        ConfigurableApplicationContext plans = PlansApplication.builder().properties(host.loggingDefaults()).run(args);
        ConfigurableApplicationContext habits = HabitsApplication.builder().properties(host.loggingDefaults()).run(args);
        log.info("Trading host up: market data, orders, plans and habits running");
        return new ConfigurableApplicationContext[] {marketData, oms, plans, habits};
    }
}
