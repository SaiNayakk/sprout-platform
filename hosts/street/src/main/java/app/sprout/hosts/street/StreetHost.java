package app.sprout.hosts.street;

import app.sprout.bank.BankApplication;
import app.sprout.clearing.ClearingApplication;
import app.sprout.depository.DepositoryApplication;
import app.sprout.exchange.ExchangeApplication;
import app.sprout.hosts.common.HostLogFields.HostInfo;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.ConfigurableApplicationContext;

/**
 * The street host: the outside parties Sprout deals with, simulated: Sprout Bank, the Sprout Stock
 * Exchange, the depository and the clearing corporation. Kept apart from Sprout's own hosts, as the
 * real ones are. The clearing corporation starts last: it settles through all the others.
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
        ConfigurableApplicationContext depository = DepositoryApplication.builder().properties(host.loggingDefaults()).run(args);
        ConfigurableApplicationContext clearing = ClearingApplication.builder().properties(host.loggingDefaults()).run(args);
        log.info("Street host up: Sprout Bank, the exchange, the depository and the clearing corporation running");
        return new ConfigurableApplicationContext[] {bank, exchange, depository, clearing};
    }
}
