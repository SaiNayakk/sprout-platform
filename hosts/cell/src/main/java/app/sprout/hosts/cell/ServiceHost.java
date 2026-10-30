package app.sprout.hosts.cell;

import app.sprout.accounts.AccountsApplication;
import app.sprout.bank.BankApplication;
import app.sprout.clearing.ClearingApplication;
import app.sprout.depository.DepositoryApplication;
import app.sprout.exchange.ExchangeApplication;
import app.sprout.gateway.GatewayApplication;
import app.sprout.goals.GoalsApplication;
import app.sprout.habits.HabitsApplication;
import app.sprout.hosts.common.HostLogFields.HostInfo;
import app.sprout.hosts.common.NoDatabase;
import app.sprout.identity.IdentityApplication;
import app.sprout.ledger.LedgerApplication;
import app.sprout.marketdata.MarketDataApplication;
import app.sprout.oms.OmsApplication;
import app.sprout.payments.PaymentsApplication;
import app.sprout.plans.PlansApplication;
import app.sprout.recon.ReconApplication;
import app.sprout.rewards.RewardsApplication;
import app.sprout.sandbox.SandboxApplication;
import app.sprout.settlement.SettlementApplication;
import app.sprout.statements.StatementsApplication;
import java.util.Map;
import java.util.function.Supplier;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;

/**
 * One service in its own JVM, named by {@code SPROUT_SERVICE}: the "one process per service" shape of the deployment
 * shapes experiment (docs/architecture/shapes.md). Production never runs this; the four hosts and the cell host are
 * the shapes Sprout runs. It exists so the same code can be measured as nineteen processes as well as four and one.
 */
public final class ServiceHost {

    private static final Logger log = LoggerFactory.getLogger(ServiceHost.class);

    private static final Map<String, Supplier<SpringApplicationBuilder>> SERVICES = Map.ofEntries(
            Map.entry("identity", IdentityApplication::builder),
            Map.entry("gateway", () -> GatewayApplication.builder().properties(
                    "spring.autoconfigure.exclude=" + NoDatabase.EXCLUDES,
                    "spring.config.additional-location=classpath:/edge-gateway-routes.yml")),
            Map.entry("sandbox", SandboxApplication::builder),
            Map.entry("marketdata", () -> MarketDataApplication.builder().properties("spring.autoconfigure.exclude=" + NoDatabase.EXCLUDES)),
            Map.entry("oms", OmsApplication::builder),
            Map.entry("plans", PlansApplication::builder),
            Map.entry("habits", HabitsApplication::builder),
            Map.entry("rewards", RewardsApplication::builder),
            Map.entry("ledger", LedgerApplication::builder),
            Map.entry("accounts", AccountsApplication::builder),
            Map.entry("payments", PaymentsApplication::builder),
            Map.entry("settlement", SettlementApplication::builder),
            Map.entry("statements", () -> StatementsApplication.builder().properties("spring.autoconfigure.exclude=" + NoDatabase.EXCLUDES)),
            Map.entry("recon", ReconApplication::builder),
            Map.entry("goals", GoalsApplication::builder),
            Map.entry("bank", BankApplication::builder),
            Map.entry("exchange", ExchangeApplication::builder),
            Map.entry("depository", DepositoryApplication::builder),
            Map.entry("clearing", ClearingApplication::builder));

    private ServiceHost() {}

    public static void main(String[] args) {
        String name = System.getenv().getOrDefault("SPROUT_SERVICE", "");
        Supplier<SpringApplicationBuilder> service = SERVICES.get(name);
        if (service == null) {
            log.error("SPROUT_SERVICE must name one of {}, not '{}'", SERVICES.keySet(), name);
            System.exit(2);
        }
        try {
            ConfigurableApplicationContext context = service.get().properties(HostInfo.load().loggingDefaults()).run(args);
            log.info("Service host up: {} running alone in its JVM ({})", name, context.getId());
        } catch (RuntimeException e) {
            log.error("The {} service couldn't start; exiting so it gets restarted", name, e);
            System.exit(1);
        }
    }
}
