package app.sprout.hosts.edge;

import app.sprout.gateway.GatewayApplication;
import app.sprout.hosts.common.HostLogFields.HostInfo;
import app.sprout.hosts.common.NoDatabase;
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
                .properties("spring.autoconfigure.exclude=" + NoDatabase.EXCLUDES,   // the gateway has no database
                        // this deployment's routes replace the gateway's built-in list
                        "spring.config.additional-location=classpath:/edge-gateway-routes.yml")
                .run(args);
        int signIns = Integer.parseInt(System.getenv().getOrDefault("EDGE_WARMUP_SIGNINS", "300"));
        if (signIns > 0) {
            WarmUp.run(identity, gateway, signIns);
        }
        // the public sandbox's fictional customers, only where this deployment is the sandbox
        if (Boolean.parseBoolean(System.getenv().getOrDefault("SPROUT_SANDBOX", "false"))) {
            ConfigurableApplicationContext sandbox = app.sprout.sandbox.SandboxApplication.builder().properties(host.loggingDefaults()).run(args);
            log.info("Edge host up: identity, gateway and the sandbox running in one JVM");
            return new ConfigurableApplicationContext[] {identity, gateway, sandbox};
        }
        log.info("Edge host up: identity and gateway running in one JVM");
        return new ConfigurableApplicationContext[] {identity, gateway};
    }
}
