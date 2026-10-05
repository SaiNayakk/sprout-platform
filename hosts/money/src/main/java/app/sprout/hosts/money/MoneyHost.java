package app.sprout.hosts.money;

import app.sprout.accounts.AccountsApplication;
import app.sprout.hosts.common.HostLogFields.HostInfo;
import app.sprout.ledger.LedgerApplication;
import app.sprout.payments.PaymentsApplication;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.ConfigurableApplicationContext;

/**
 * The money host: the ledger, accounts and payments, each in its own Spring context with its own
 * config, port and database schema. They share a JVM because a payment needs all three: if one is
 * down, payments can't move money either way.
 */
public final class MoneyHost {

    private static final Logger log = LoggerFactory.getLogger(MoneyHost.class);

    private MoneyHost() {}

    public static void main(String[] args) {
        try {
            start(args);
        } catch (RuntimeException e) {
            log.error("The money host couldn't start; exiting so it gets restarted", e);
            System.exit(1);
        }
    }

    /** The ledger first: it's the source of truth the other two write to. */
    public static ConfigurableApplicationContext[] start(String... args) {
        HostInfo host = HostInfo.load();
        ConfigurableApplicationContext ledger = LedgerApplication.builder().properties(host.loggingDefaults()).run(args);
        ConfigurableApplicationContext accounts = AccountsApplication.builder().properties(host.loggingDefaults()).run(args);
        ConfigurableApplicationContext payments = PaymentsApplication.builder().properties(host.loggingDefaults()).run(args);
        log.info("Money host up: ledger, accounts and payments running in one JVM");
        return new ConfigurableApplicationContext[] {ledger, accounts, payments};
    }
}
