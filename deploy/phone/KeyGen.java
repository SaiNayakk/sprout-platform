import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.util.Base64;

/**
 * Generates identity's RSA token-signing key as PEM (the phone has no openssl).
 * Run as a single-file program: java KeyGen.java ~/.sprout/keys/signing.pem
 */
public class KeyGen {
    public static void main(String[] args) throws Exception {
        KeyPairGenerator g = KeyPairGenerator.getInstance("RSA");
        g.initialize(2048);
        KeyPair kp = g.generateKeyPair();
        Base64.Encoder b64 = Base64.getMimeEncoder(64, "\n".getBytes());
        String pem = "-----BEGIN PUBLIC KEY-----\n" + b64.encodeToString(kp.getPublic().getEncoded())
                + "\n-----END PUBLIC KEY-----\n-----BEGIN PRIVATE KEY-----\n"
                + b64.encodeToString(kp.getPrivate().getEncoded()) + "\n-----END PRIVATE KEY-----\n";
        Path out = Path.of(args[0]);
        Path tmp = out.resolveSibling(out.getFileName() + ".tmp");
        Files.writeString(tmp, pem);
        Files.move(tmp, out, java.nio.file.StandardCopyOption.REPLACE_EXISTING);
    }
}
