package app.sprout.hosts.common;

import static org.assertj.core.api.Assertions.assertThat;

import app.sprout.hosts.common.HostLogFields.HostInfo;
import java.util.Map;
import org.junit.jupiter.api.Test;

class HostLogFieldsTest {

    final HostLogFields fields = new HostLogFields(Map.of(
            "app.sprout.identity", new String[] {"sprout-identity", "0.2.1"},
            "app.sprout.gateway", new String[] {"sprout-gateway", "0.2.4"}));

    @Test
    void eachLineIsLabelledWithTheServiceWhoseCodeWroteIt() {
        assertThat(fields.lookup("app.sprout.gateway.ProxyController", 0)).isEqualTo("sprout-gateway");
        assertThat(fields.lookup("app.sprout.gateway.ProxyController", 1)).isEqualTo("0.2.4");
        assertThat(fields.lookup("app.sprout.identity.domain.TokenService", 0)).isEqualTo("sprout-identity");
    }

    @Test
    void frameworkCodeAndLookalikePackagesGetNoServiceLabel() {
        assertThat(fields.lookup("org.springframework.boot.SpringApplication", 0)).isNull();
        assertThat(fields.lookup("app.sprout.gatewayish.Thing", 0)).isNull();
        assertThat(fields.lookup(null, 0)).isNull();
    }

    @Test
    void theBuildFillsInTheHostAndItsServicesFromTheManifest() {
        HostInfo info = HostInfo.load(); // the test copy of sprout-host.properties
        assertThat(info.name()).isEqualTo("test-host");
        assertThat(info.services().get("app.sprout.identity")).containsExactly("sprout-identity", "9.9.9");
        assertThat(info.loggingDefaults()).containsEntry("logging.structured.json.customizer", HostLogFields.class.getName());
    }
}
