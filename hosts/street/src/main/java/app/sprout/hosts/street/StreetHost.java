package app.sprout.hosts.street;

import app.sprout.bank.BankApplication;
import app.sprout.exchange.ExchangeApplication;
import app.sprout.hosts.common.HostLogFields.HostInfo;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.ConfigurableApplicationContext;

/**
 * The street host: the outside parties Sprout deals with, simulated. Sprout Bank and the Sprout Stock
 * Exchange; clearing and the depository as they arrive. Kept apart from Sprout's own hosts, as the
 * real ones are.
 */
public final class StreetHost {

    private static final Logger log = LoggerFactory.getLogger(StreetHost.class);

    private StreetHost() {}

    public static void main(String[] args) {
        try {
            start(args);
        } catch (RuntimeException e) {
            log.error("The street host couldn't start; exiting so it gets restarted", e);
            System.exit(1);
        }
    }

    public static ConfigurableApplicationContext[] start(String... args) {
        HostInfo host = HostInfo.load();
        ConfigurableApplicationContext bank = BankApplication.builder().properties(host.loggingDefaults()).run(args);
        ConfigurableApplicationContext exchange = ExchangeApplication.builder().properties(host.loggingDefaults()).run(args);
        log.info("Street host up: Sprout Bank and the exchange running");
        return new ConfigurableApplicationContext[] {bank, exchange};
    }
}
