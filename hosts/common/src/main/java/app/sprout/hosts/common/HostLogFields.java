package app.sprout.hosts.common;

import ch.qos.logback.classic.spi.ILoggingEvent;
import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import org.springframework.boot.json.JsonWriter;
import org.springframework.boot.logging.structured.StructuredLoggingJsonMembersCustomizer;

/**
 * Adds {@code sprout.service} and {@code sprout.service.version} to every JSON log line, worked out
 * from the code that wrote it.
 *
 * <p>In a shared host, logging belongs to the JVM, not to a service: before this, every line was
 * labelled with whichever service started first, and with the host jar's version. The host's own
 * name and version still go in ECS {@code service.name}/{@code service.version} (the process), and
 * these fields say which service inside it wrote the line. The mapping comes from
 * {@code sprout-host.properties}, which the build fills in from the host's release manifest.
 */
public class HostLogFields implements StructuredLoggingJsonMembersCustomizer<ILoggingEvent> {

    /** Longest package first, so a more specific package always wins. */
    private final List<Map.Entry<String, String[]>> services;

    public HostLogFields() {
        this(HostInfo.load().services());
    }

    HostLogFields(Map<String, String[]> byPackage) {
        this.services = byPackage.entrySet().stream()
                .sorted(Comparator.comparingInt((Map.Entry<String, String[]> e) -> e.getKey().length()).reversed())
                .toList();
    }

    @Override
    public void customize(JsonWriter.Members<ILoggingEvent> members) {
        members.add("sprout.service", (ILoggingEvent e) -> lookup(e.getLoggerName(), 0)).whenNotNull();
        members.add("sprout.service.version", (ILoggingEvent e) -> lookup(e.getLoggerName(), 1)).whenNotNull();
    }

    /** The service (0) or its version (1) for a logger, or null for framework and library code. */
    String lookup(String logger, int field) {
        if (logger == null) {
            return null;
        }
        for (Map.Entry<String, String[]> e : services) {
            if (logger.equals(e.getKey()) || logger.startsWith(e.getKey() + ".")) {
                return e.getValue()[field];
            }
        }
        return null;
    }

    /** The host's name, version and services, as the build recorded them. */
    public record HostInfo(String name, String version, Map<String, String[]> services) {

        static final String RESOURCE = "sprout-host.properties";

        public static HostInfo load() {
            Properties p = new Properties();
            try (InputStream in = HostLogFields.class.getClassLoader().getResourceAsStream(RESOURCE)) {
                if (in == null) {
                    throw new IllegalStateException(RESOURCE + " is missing from the host jar");
                }
                p.load(in);
            } catch (IOException e) {
                throw new UncheckedIOException(e);
            }
            Map<String, String[]> services = new java.util.LinkedHashMap<>();
            for (String key : p.stringPropertyNames()) {
                if (key.startsWith("package.")) {
                    String[] serviceAndVersion = p.getProperty(key).trim().split("\\s+");
                    services.put(key.substring("package.".length()), serviceAndVersion);
                }
            }
            return new HostInfo(p.getProperty("host.name"), p.getProperty("host.version"), services);
        }

        /** Properties every service context in this host starts with, so they all log the same way. */
        public Map<String, Object> loggingDefaults() {
            return Map.of(
                    "logging.structured.ecs.service.name", name,
                    "logging.structured.ecs.service.version", version,
                    "logging.structured.json.customizer", HostLogFields.class.getName());
        }
    }
}
