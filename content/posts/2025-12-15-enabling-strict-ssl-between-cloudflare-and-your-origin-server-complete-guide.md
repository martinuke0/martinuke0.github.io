---
title: "Enabling Strict SSL Between Cloudflare and Your Origin Server: Complete Guide"
date: "2025-12-15T09:02:18.418"
draft: false
tags: ["Cloudflare", "SSL/TLS", "Security", "Origin Certificate", "Web Security"]
---

In **Full (strict)** mode, Cloudflare encrypts all traffic between visitors and your origin server while strictly validating the origin's SSL certificate to ensure it's valid, unexpired, and issued by a trusted authority like a public CA or Cloudflare's Origin CA.[1][4][5] This setup provides end-to-end encryption without exposing your server to unverified connections, preventing man-in-the-middle attacks.[4]

## Why Use Full (Strict) SSL Mode?

Cloudflare offers several SSL/TLS encryption modes, but **Full (strict)** stands out for maximum security:

- **Flexible**: Encrypts browser-to-Cloudflare but uses HTTP to origin—vulnerable to attacks post-Cloudflare.[5]
- **Full**: Encrypts both legs but doesn't validate the origin certificate, allowing self-signed certs.[5][6]
- **Full (strict)**: Like Full, but verifies the origin certificate's validity, hostname match, and trust chain.[1][4][5]
- **Strict (SSL-Only Origin Pull)**: Always uses HTTPS to origin with validation, ideal for Enterprise users.[2]

> **Key Benefit**: Full (strict) is recommended "whenever possible" for non-Enterprise users as it balances security and compatibility.[4][5]

Without strict validation, attackers could intercept traffic between Cloudflare and your server if using invalid certs.[1]

## Prerequisites for Full (Strict) Mode

Before enabling, ensure your origin server meets these requirements:[4]

- Supports HTTPS on **port 443**.
- Presents a certificate that is:
  - Unexpired (`notBeforeDate < now() < notAfterDate`).
  - Issued by a publicly trusted CA (e.g., Let's Encrypt) or Cloudflare Origin CA.
  - Matches the hostname in Common Name (CN) or Subject Alternative Name (SAN).[4]
  
Failure results in **526 errors** (Invalid SSL Certificate).[4]

## Step-by-Step: Generating a Cloudflare Origin Certificate

Cloudflare's free Origin CA certificates are perfect for this—they're trusted only by Cloudflare, optimizing for proxy setups.[1]

1. Log into the Cloudflare dashboard.
2. Select your domain > **SSL/TLS** > **Origin Server**.
3. Click **Create Certificate**.
4. Choose **"Generate private key and CSR with Cloudflare"** (default).[1]
5. Select **RSA 2048** for private key type.
6. Add hostnames: e.g., `example.com` and `*.example.com` (pre-filled).[1]
7. Set validity (up to 15 years) and generate.

Download the **Certificate** (`.pem`) and **Private Key** (`.key`). Store securely.[1]

## Configuring Your Origin Server: Apache Example

Here's a detailed Apache setup using the Origin Certificate.[1]

### 1. Install Certificate Files
```
sudo mkdir -p /etc/ssl/cloudflare
sudo nano /etc/ssl/cloudflare/example.com.crt  # Paste certificate
sudo nano /etc/ssl/cloudflare/example.com.key  # Paste private key
sudo chmod 600 /etc/ssl/cloudflare/example.com.key
```

### 2. Update VirtualHost Configuration
Edit `/etc/apache2/sites-available/example.com.conf`:

```apache
<VirtualHost *:80>
    ServerName example.com
    Redirect permanent / https://example.com/
</VirtualHost>

<VirtualHost *:443>
    ServerName example.com
    
    SSLEngine on
    SSLCertificateFile /etc/ssl/cloudflare/example.com.crt
    SSLCertificateKeyFile /etc/ssl/cloudflare/example.com.key
    
    # Optional: HSTS for extra security
    Header always set Strict-Transport-Security "max-age=31536000; includeSubDomains"
    
    DocumentRoot /var/www/html
    # Other directives...
</VirtualHost>
```

### 3. Enable and Restart
```
sudo a2enmod ssl
sudo a2ensite example.com.conf
sudo systemctl restart apache2
```

> **Note**: Replace paths and domain. For Nginx or other servers, adapt SSLCertificateFile/KeyFile directives similarly.[1]

## Enabling Full (Strict) Mode in Cloudflare Dashboard

1. Go to **SSL/TLS** > **Overview**.
2. Set **Encryption Mode** to **Full (strict)**.[1][4]
3. Save changes.

Via API:
```
PATCH /zones/:zone_id/settings/ssl
{"value": "strict"}
```
[2][4][5]

Cloudflare's **Automatic SSL/TLS** may gradually upgrade modes, rolling back on errors.[5]

## Alternative: Using Let's Encrypt with Full (Strict)

If preferring public CAs like Let's Encrypt:

- Install cert via Certbot: `certbot --apache`.
- Ensure it covers your domain.
- Enable Full (strict)—Cloudflare trusts Let's Encrypt.[8][4]

Community recommends this for optimal setup without disabling Universal SSL.[8]

## Additional Security: Enable HSTS

Complement with **HTTP Strict Transport Security (HSTS)** to prevent downgrade attacks:[3]

1. **SSL/TLS** > **Edge Certificates**.
2. Enable **HSTS** > Configure:
   | Setting          | Recommendation          |
   |------------------|-------------------------|
   | Enable HSTS      | On                     |
   | Max Age          | 6-12 months            |
   | Include Subdomains | Yes (if applicable)   |
   | Preload          | Optional for production|

3. Save. Avoid DNS unproxying or SSL disable post-enable.[3]

## Troubleshooting Common Issues

- **526 Error**: Invalid origin cert—check expiry, hostname, port 443.[4]
- **525 Error**: Origin SSL handshake failed—verify server HTTPS.
- **Mixed Content**: Ensure all resources load over HTTPS.
- Test with: `curl -v https://example.com` and Cloudflare diagnostics.

Monitor Cloudflare Analytics for TLS errors.[1]

## Best Practices and Considerations

- Use **Strict (SSL-Only Origin Pull)** for always-HTTPS origins (Enterprise).[2]
- Rotate Origin Certificates before expiry.
- For non-443 ports, use Cloudflare Spectrum (Enterprise).[4]
- Avoid Flexible in production—exposes origin HTTP.[5][7]

| Mode             | Origin Validation | Always HTTPS to Origin | Best For                  |
|------------------|-------------------|------------------------|---------------------------|
| Full            | No               | No                     | Self-signed certs[6]     |
| **Full (strict)** | Yes              | No                     | Most users[4]            |
| Strict Pull     | Yes              | Yes                    | Enterprise[2]            |

## Conclusion

Enabling **Full (strict)** SSL between Cloudflare and your origin delivers robust, verified end-to-end encryption, essential for modern web security.[1][4] Follow these steps—generate an Origin CA cert, configure your server, switch modes, and layer HSTS—for a fortified setup. Regularly audit certificates to maintain protection. Your site will thank you with fewer vulnerabilities and better compliance.

This configuration scales from small blogs to enterprises, ensuring traffic stays encrypted where it matters most.[5]