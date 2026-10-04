package app.sprout.hosts.edge;

import app.sprout.gateway.GatewayApplication;
import app.sprout.hosts.common.HostLogFields.HostInfo;
import app.sprout.identity.IdentityApplication;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.ConfigurableApplicationContext;

/**
 * Runs identity and the gateway in one JVM, as two separate Spring application contexts: each
 * has its own beans, config file ({@code identity.yml}, {@code gateway.yml}), port and
 * database settings, and they talk over HTTP exactly as they would in separate processes.
 * Sharing the JVM only shares the framework's loaded classes, which is what saves the memory
 * (measured: about 8 MB per extra service instead of about 140 MB per JVM).
 *
 * <p>If either service fails to start, the host exits non-zero so the supervisor restarts it.
 */
public final class EdgeHost {

    private static final Logger log = LoggerFactory.getLogger(EdgeHost.class);

    /** The gateway has no database; don't let the shared classpath give it one. */
    static final String GATEWAY_EXCLUDES = String.join(",",
            "org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration",
            "org.springframework.boot.autoconfigure.jdbc.DataSourceTransactionManagerAutoConfiguration",
            "org.springframework.boot.autoconfigure.jdbc.JdbcTemplateAutoConfiguration",
            "org.springframework.boot.autoconfigure.jdbc.JdbcClientAutoConfiguration",
            "org.springframework.boot.autoconfigure.flyway.FlywayAutoConfiguration");

    private EdgeHost() {}

    public static void main(String[] args) {
        try {
            start(args);
        } catch (RuntimeException e) {
            log.error("The edge host couldn't start; exiting so it gets restarted", e);
            System.exit(1);
        }
    }

    /** Starts identity first (the gateway fetches its keys from it), then the gateway. */
    public static ConfigurableApplicationContext[] start(String... args) {
        HostInfo host = HostInfo.load();
        ConfigurableApplicationContext identity = IdentityApplication.builder()
                .properties(host.loggingDefaults())
                .run(args);
        ConfigurableApplicationContext gateway = GatewayApplication.builder()
                .properties(host.loggingDefaults())
                .properties("spring.autoconfigure.exclude=" + GATEWAY_EXCLUDES)
                .run(args);
        int signIns = Integer.parseInt(System.getenv().getOrDefault("EDGE_WARMUP_SIGNINS", "300"));
        if (signIns > 0) {
            WarmUp.run(identity, gateway, signIns);
        }
        log.info("Edge host up: identity and gateway running in one JVM");
        return new ConfigurableApplicationContext[] {identity, gateway};
    }
}
