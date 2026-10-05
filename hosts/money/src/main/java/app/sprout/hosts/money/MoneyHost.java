package app.sprout.hosts.money;

import app.sprout.accounts.AccountsApplication;
import app.sprout.hosts.common.HostLogFields.HostInfo;
import app.sprout.hosts.common.NoDatabase;
import app.sprout.ledger.LedgerApplication;
import app.sprout.payments.PaymentsApplication;
import app.sprout.recon.ReconApplication;
import app.sprout.settlement.SettlementApplication;
import app.sprout.statements.StatementsApplication;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.ConfigurableApplicationContext;

/**
 * The money host: the ledger, accounts, payments, the settlement back office, statements and
 * reconciliation, each in its own Spring context with its own config, port and database schema
 * (statements has none). They share a JVM because they all move or report money through the ledger:
 * if it is down, none of them can work anyway.
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

    /** The ledger first: it's the source of truth the others write to. */
    public static ConfigurableApplicationContext[] start(String... args) {
        HostInfo host = HostInfo.load();
        ConfigurableApplicationContext ledger = LedgerApplication.builder().properties(host.loggingDefaults()).run(args);
        ConfigurableApplicationContext accounts = AccountsApplication.builder().properties(host.loggingDefaults()).run(args);
        ConfigurableApplicationContext payments = PaymentsApplication.builder().properties(host.loggingDefaults()).run(args);
        ConfigurableApplicationContext settlement = SettlementApplication.builder().properties(host.loggingDefaults()).run(args);
        ConfigurableApplicationContext statements = StatementsApplication.builder().properties(host.loggingDefaults())
                .properties("spring.autoconfigure.exclude=" + NoDatabase.EXCLUDES)   // statements reads the books; it has no database
                .run(args);
        ConfigurableApplicationContext recon = ReconApplication.builder().properties(host.loggingDefaults()).run(args);
        log.info("Money host up: ledger, accounts, payments, settlement, statements and recon running in one JVM");
        return new ConfigurableApplicationContext[] {ledger, accounts, payments, settlement, statements, recon};
    }
}
