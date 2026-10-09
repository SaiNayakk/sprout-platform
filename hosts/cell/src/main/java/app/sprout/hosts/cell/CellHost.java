package app.sprout.hosts.cell;

import app.sprout.hosts.edge.EdgeHost;
import app.sprout.hosts.money.MoneyHost;
import app.sprout.hosts.street.StreetHost;
import app.sprout.hosts.trading.TradingHost;
import java.util.ArrayList;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.ConfigurableApplicationContext;

/**
 * Every Sprout service in one JVM: what a cell runs for the other cell's customers when that cell is lost (ADR-027).
 *
 * <p>The four hosts are separate JVMs on purpose (a fault in one can't take sign-in down with it). A standby is
 * different: it is idle until the moment it is needed, and it has to fit beside the cell's own services on a phone or
 * a laptop with little memory to spare. One JVM saves each process's own overhead three times over. It starts the
 * hosts' services in the order their dependencies need: market data first, the edge (sign-in and the gateway) last.
 */
public final class CellHost {

    private static final Logger log = LoggerFactory.getLogger(CellHost.class);

    private CellHost() {}

    public static void main(String[] args) {
        try {
            start(args);
        } catch (RuntimeException e) {
            log.error("The cell host couldn't start; exiting so it gets restarted", e);
            System.exit(1);
        }
    }

    public static ConfigurableApplicationContext[] start(String... args) {
        List<ConfigurableApplicationContext> all = new ArrayList<>();
        all.addAll(List.of(TradingHost.start(args)));
        all.addAll(List.of(StreetHost.start(args)));
        all.addAll(List.of(MoneyHost.start(args)));
        all.addAll(List.of(EdgeHost.start(args)));
        log.info("Cell host up: all {} services running in one JVM", all.size());
        return all.toArray(ConfigurableApplicationContext[]::new);
    }
}
