package app.sprout.hosts.common;

/**
 * For a service without a database that shares a JVM with one that has one: the shared classpath
 * would otherwise make Spring Boot try to configure a database for it too, and fail without a URL.
 */
public final class NoDatabase {

    /** Pass as {@code spring.autoconfigure.exclude=} when starting the service's context. */
    public static final String EXCLUDES = String.join(",",
            "org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration",
            "org.springframework.boot.autoconfigure.jdbc.DataSourceTransactionManagerAutoConfiguration",
            "org.springframework.boot.autoconfigure.jdbc.JdbcTemplateAutoConfiguration",
            "org.springframework.boot.autoconfigure.jdbc.JdbcClientAutoConfiguration",
            "org.springframework.boot.autoconfigure.flyway.FlywayAutoConfiguration");

    private NoDatabase() {}
}
