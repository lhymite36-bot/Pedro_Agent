package com.pedro.agent;

import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** 1.5.12: the user's own Gemini key, encrypted with an Android Keystore AES-GCM key.
 *  The key never leaves the phone: not in git, not in Supabase, not sent to the PC. */
final class SecureStore {
    static final String ALIAS = "pedbot_gemini_v1", PREF = "gk_enc";
    private final SharedPreferences prefs;
    SecureStore(SharedPreferences p) { prefs = p; }

    private SecretKey key() throws Exception {
        KeyStore ks = KeyStore.getInstance("AndroidKeyStore"); ks.load(null);
        if (ks.containsAlias(ALIAS)) return ((KeyStore.SecretKeyEntry) ks.getEntry(ALIAS, null)).getSecretKey();
        KeyGenerator g = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        g.init(new KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256).build());
        return g.generateKey();
    }

    boolean has() { return !prefs.getString(PREF, "").isEmpty(); }

    void put(String secret) throws Exception {
        Cipher c = Cipher.getInstance("AES/GCM/NoPadding"); c.init(Cipher.ENCRYPT_MODE, key());
        byte[] iv = c.getIV(), ct = c.doFinal(secret.getBytes("UTF-8"));
        byte[] all = new byte[iv.length + ct.length];
        System.arraycopy(iv, 0, all, 0, iv.length); System.arraycopy(ct, 0, all, iv.length, ct.length);
        prefs.edit().putString(PREF, Base64.encodeToString(all, Base64.NO_WRAP)).apply();
    }

    String get() {
        String raw = prefs.getString(PREF, "");
        if (raw.isEmpty()) return "";
        try {
            byte[] all = Base64.decode(raw, Base64.NO_WRAP);
            Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
            c.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, all, 0, 12));
            return new String(c.doFinal(all, 12, all.length - 12), "UTF-8");
        } catch (Exception e) { return ""; }
    }

    void clear() { prefs.edit().remove(PREF).apply(); }
}
