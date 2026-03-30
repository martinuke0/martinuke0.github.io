---
title: "Mastering cPanel: A Comprehensive Guide for Web Hosts and System Administrators"
date: "2026-03-30T11:25:38.558"
draft: false
tags: ["cPanel", "Web Hosting", "Server Management", "Linux", "Control Panel"]
---

## Table of Contents
1. [Introduction](#introduction)  
2. [What Is cPanel?](#what-is-cpanel)  
3. [A Brief History & Licensing Model](#a-brief-history--licensing-model)  
4. [Architecture Overview: cPanel & WHM](#architecture-overview-cpanel--whm)  
5. [Core Features Explained]  
   - 5.1 [Domain & DNS Management](#domain--dns-management)  
   - 5.2 [Email Suite](#email-suite)  
   - 5.3 [File Management](#file-management)  
   - 5.4 [Databases (MySQL/MariaDB & PostgreSQL)](#databases-mysqlmariadb--postgresql)  
   - 5.5 [Security Tools](#security-tools)  
   - 5.6 [Backup & Restoration](#backup--restoration)  
   - 5.7 [Software Installers (Softaculous, SitePad, etc.)](#software-installers)  
6. [Navigating the cPanel Interface: A Hands‑On Walkthrough](#navigating-the-cpanel-interface)  
7. [Advanced Administration]  
   - 7.1 [Command‑Line Interaction (cPanel CLI)](#command‑line-interaction)  
   - 7.2 [cPanel API (UAPI & XML‑API)](#cpanel-api)  
   - 7.3 [Automation with Cron & Scripts](#automation-with-cron--scripts)  
8. [Comparing cPanel with Alternative Control Panels](#comparing-cpanel-with-alternatives)  
9. [Best Practices for Security & Performance](#best-practices)  
10 [Troubleshooting Common Issues](#troubleshooting-common-issues)  
11 [Migrating to / from cPanel](#migrating)  
12 [Pricing, Licensing, and Community Support](#pricing-licensing)  
13 [Future Trends & Emerging Features](#future-trends)  
14 [Conclusion](#conclusion)  
15 [Resources](#resources)  

---

## Introduction

For anyone who has ever managed a shared‑hosting environment, the word **cPanel** instantly conjures an image of a sleek, web‑based dashboard packed with icons, drop‑down menus, and a seemingly endless list of tools. Since its debut in the early 2000s, cPanel has become the de‑facto standard for Linux‑based web hosting control panels, powering millions of domains worldwide.

But cPanel is more than a pretty UI. It is a mature ecosystem that couples a powerful **Web Host Manager (WHM)** back‑end, a robust API layer, and a suite of security and automation utilities. Understanding how each component works—and how to wield them—can dramatically reduce the time you spend on routine server tasks, improve the reliability of your hosted sites, and give you a professional edge when dealing with clients.

This guide dives deep into the inner workings of cPanel, from the basics of logging in to advanced scripting with the API. Whether you’re a newcomer looking to get comfortable with the interface, a seasoned sysadmin aiming to automate repetitive tasks, or a business owner evaluating whether cPanel is the right investment, the sections below will provide actionable insight backed by real‑world examples.

---

## What Is cPanel?

cPanel is a **commercial web‑hosting control panel** that provides a graphical interface and automation tools designed to simplify the process of hosting a website. It runs on **CentOS, CloudLinux, AlmaLinux, and other RHEL‑compatible distributions** and requires **Apache, Nginx, or LiteSpeed** as the underlying web server.

Key characteristics:

| Feature | Description |
|---------|-------------|
| **Web‑based UI** | Accessible from any modern browser, no client software required. |
| **Multi‑user architecture** | Separate accounts for end‑users (cPanel) and server administrators (WHM). |
| **Extensibility** | Plugins, themes, and API endpoints allow custom functionality. |
| **Automation** | Built‑in installers (Softaculous, Installatron), backup schedules, and cron management. |
| **Security** | Integrated CSF/LFD firewall, ModSecurity, password‑strength enforcement, and two‑factor authentication (2FA). |

At its core, cPanel abstracts low‑level Linux commands (e.g., `httpd`, `mysqld`, `postfix`) into friendly forms, reducing the need for manual configuration files. However, the platform still respects the underlying OS, allowing administrators to drop to the shell when needed.

---

## A Brief History & Licensing Model

cPanel, Inc. was founded in 1996 by **John Nick Koston and Jason R. Kline** as a simple webmail interface. The product evolved rapidly, adding FTP, DNS, and database management. By 2003, cPanel introduced **WHM (Web Host Manager)**, enabling hosting providers to manage multiple cPanel accounts from a single interface.

### Licensing Evolution

| Year | Milestone |
|------|-----------|
| 2000 | First commercial license (per‑server). |
| 2008 | Introduction of **cPanel & WHM Solo**, targeting small businesses. |
| 2015 | Shift to **cPanel & WHM Pro**, adding reseller features and API enhancements. |
| 2020 | Move to **monthly subscription model** for new accounts, while existing perpetual licenses remained honored. |
| 2024 | **cPanel 120** release, focusing on AI‑driven security suggestions and container‑aware backups. |

Licensing is typically **per‑server**, with tiered pricing based on the number of accounts allowed (e.g., Solo – up to 5 accounts, Pro – up to 30, Premier – unlimited). The monthly subscription model provides flexibility for cloud‑based VMs that spin up and down frequently.

---

## Architecture Overview: cPanel & WHM

Understanding the relationship between cPanel and WHM is crucial for effective administration.

```
+------------------------+        +------------------------+
|      WHM (Root)        | <----> |   cPanel (User)        |
|  - Account Creation    |        |  - Domain Management   |
|  - Package Management  |        |  - Email, Files, DB    |
|  - Server Settings     |        |  - SSL/TLS             |
+------------------------+        +------------------------+
          ^   ^                               ^
          |   |                               |
          |   +----------+      +-------------+
          |              |      |
          v              v      v
+-------------------+  +-------------------+
|  cPanel API (UAPI)|  |  System Services  |
|  - XML‑API        |  |  - Apache/Nginx   |
|  - CLI Tools      |  |  - MySQL/MariaDB  |
+-------------------+  +-------------------+
```

* **WHM (Web Host Manager)** runs as the **root** user (or a privileged reseller). It provides:
  * Account creation (`createacct`), suspension, and termination.
  * Package definitions (disk quota, bandwidth limits, feature lists).
  * Server‑wide configuration (PHP versions, Apache modules, security policies).

* **cPanel** runs under the **cPanel user** (e.g., `example.com`). It offers:
  * Self‑service tools for domain, email, and file management.
  * Access to **phpMyAdmin**, **File Manager**, **SSL/TLS** configuration.

* **Underlying services** (Apache/Nginx, Dovecot, Exim, MySQL) are managed either through WHM or directly via command‑line scripts. cPanel interacts with these services via **hooks** and **configuration templates**.

---

## Core Features Explained

### Domain & DNS Management

cPanel's **Zone Editor** lets users add, edit, and delete DNS records for any domain hosted on the server. Typical record types include A, CNAME, MX, TXT, and SRV.

*Example: Adding an A record for `blog.example.com`*

1. Navigate to **Domains → Zone Editor**.
2. Click **Add Record** → select **A**.
3. Input `blog` as the name and the target IP (e.g., `192.0.2.45`).
4. Save.

cPanel also supports **Addon Domains**, **Parked (Alias) Domains**, and **Sub‑domains**, each creating their own document root under `/home/username/public_html/`.

### Email Suite

cPanel bundles **Exim** (SMTP) and **Dovecot** (IMAP/POP3) into a friendly interface:

| Tool | Primary Use |
|------|--------------|
| **Email Accounts** | Create mailbox addresses (`user@example.com`). |
| **Forwarders** | Redirect inbound mail to another address. |
| **Autoresponders** | Automatic vacation or welcome messages. |
| **Spam Filters** | Integration with SpamAssassin and BoxTrapper. |
| **DKIM & SPF** | Built‑in DNS record generators for email authentication. |

*Practical tip*: Enable **DKIM** per domain under **Email → Authentication**. This reduces the likelihood of outbound mail being marked as spam.

### File Management

The **File Manager** offers a web‑based GUI for file operations (upload, edit, permissions). It mirrors the underlying Linux file system:

- **Document Root**: `/home/username/public_html/`
- **Logs**: `/usr/local/apache/logs/`
- **Backups**: `/home/username/backups/`

For power users, the **cPanel CLI** provides commands such as `uapi --user=username Filemanager upload_file path=/home/username/public_html/index.html source=/tmp/uploaded.html`.

### Databases (MySQL/MariaDB & PostgreSQL)

cPanel supports both **MySQL/MariaDB** and **PostgreSQL**:

- **MySQL/MariaDB**: Create databases, users, and assign privileges via **MySQL® Databases**.
- **phpMyAdmin**: Full‑featured web UI for query execution, export, and import.
- **PostgreSQL**: Managed through **PostgreSQL® Databases** and **phpPgAdmin** (if installed).

*Example: Creating a MySQL database via the CLI*

```bash
# Create a new database named shopdb for user 'shopuser'
uapi --user=shopowner Mysql create_database name=shopdb
uapi --user=shopowner Mysql create_user name=shopuser password='StrongPass!2026'
uapi --user=shopowner Mysql set_privileges user=shopuser database=shopdb privileges=ALL
```

### Security Tools

cPanel includes a suite of security utilities:

| Tool | Description |
|------|-------------|
| **CSF/LFD** | ConfigServer Security & Firewall with real‑time intrusion detection. |
| **ModSecurity** | Web‑application firewall (WAF) with OWASP CRS rules. |
| **Password Strength** | Enforced via **Password Strength Configuration**. |
| **Two‑Factor Authentication (2FA)** | Google Authenticator or Authy integration. |
| **IP Blocker** | Block malicious IPs at the cPanel level. |
| **SSL/TLS Manager** | Auto‑install Let's Encrypt certificates, manage custom certs. |

A recommended security baseline:

1. Enable **CSF** and set `TESTING = "0"` in `/etc/csf/csf.conf`.
2. Activate **ModSecurity** with the latest CRS (Core Rule Set) ruleset.
3. Enforce **2FA** for all reseller and root accounts.
4. Deploy **AutoSSL** (Let's Encrypt) for every domain.

### Backup & Restoration

cPanel provides **Backup Wizard** and **Backup Configuration**:

- **Full account backup** (home directory, databases, email) stored in `/home/username/backups/`.
- **Incremental backups** via **cPBackups** (available on higher‑tier licenses).
- **Remote backup destinations**: FTP, SFTP, Amazon S3, Google Drive (via third‑party plugins).

*Example: Scheduling a daily full backup to an SFTP server*

```bash
# In WHM → Backup Configuration:
#   Backup Type: Compressed
#   Backup Destination: /backup (local) + SFTP
#   Schedule: Daily at 02:00 AM

# Verify backup with:
ls -lh /backup/$(date +%Y-%m-%d).tar.gz
```

### Software Installers (Softaculous, SitePad, etc.)

cPanel integrates with **Softaculous**, **Installatron**, and **SitePad** to enable one‑click installations of popular CMSs (WordPress, Joomla, Drupal), e‑commerce platforms (Magento, OpenCart), and more.

*Installation flow for WordPress via Softaculous*:

1. Click **Softaculous Apps Installer** → **WordPress**.
2. Fill in site name, admin credentials, and choose the domain/sub‑domain.
3. Click **Install** – Softaculous configures the database, writes the `wp-config.php`, and sets the correct file permissions.

---

## Navigating the cPanel Interface: A Hands‑On Walkthrough

Below is a step‑by‑step exploration of the default **cPanel 120** theme (the “Paper Lantern” predecessor is still common, but the concepts are identical).

1. **Login**  
   - URL: `https://yourserver.com:2083` (or `https://yourdomain.com/cpanel`).  
   - Use the username/password created during account provisioning.  
   - Optionally enable **2FA** on the **Security → Two‑Factor Authentication** page.

2. **Dashboard Overview**  
   - **Quick Stats**: Disk usage, bandwidth, email accounts.  
   - **Resource Usage**: CPU, memory, processes (via **Metrics → Resource Usage**).  

3. **Domain Management**  
   - **Addon Domains** → Add a new domain `example.net`.  
   - **Subdomains** → Create `blog.example.com`.  

4. **File Manager**  
   - Navigate to `public_html`.  
   - Use the **Upload** button to transfer a static `index.html`.  
   - Right‑click → **Edit** to modify files directly in the browser.  

5. **Email**  
   - **Email Accounts** → Create `info@example.com` with quota 2 GB.  
   - Enable **Spam Filters** → **SpamAssassin** status = **Enabled**.  

6. **Databases**  
   - **MySQL® Databases** → Create `mydb`.  
   - Create user `myuser` and assign to `mydb`.  
   - Launch **phpMyAdmin** → Run a test query `SELECT NOW();`.  

7. **SSL/TLS**  
   - **AutoSSL** → Enable for all domains (uses Let’s Encrypt).  
   - For a custom certificate, upload the PEM files under **Manage SSL Sites**.  

8. **Backup**  
   - **Backup Wizard** → Choose **Full Backup** → Destination: **Home Directory**.  

9. **Security**  
   - **IP Blocker** → Block `203.0.113.45`.  
   - **Password Strength** → Set minimum score to **Strong**.  

10. **Software**  
    - **Softaculous Apps Installer** → Install **WordPress** on `example.com`.  

A user familiar with these steps can accomplish 80 % of routine tasks without touching the command line.

---

## Advanced Administration

### Command‑Line Interaction (cPanel CLI)

cPanel ships with a set of **UAPI** (User API) commands accessible via the `uapi` binary. These are useful for scripting bulk operations.

*Example: Bulk creation of email accounts from a CSV file*

```bash
#!/bin/bash
# bulk-email-create.sh
# Usage: ./bulk-email-create.sh user@example.com accounts.csv

USER=$1
CSV=$2

while IFS=, read -r email password quota; do
    uapi --user="${USER}" Email add_pop email="${email}" password="${password}" quota="${quota}"
    echo "Created $email with quota ${quota}MB"
done < "${CSV}"
```

Run with:

```bash
chmod +x bulk-email-create.sh
./bulk-email-create.sh example.com /path/to/accounts.csv
```

### cPanel API (UAPI & XML‑API)

cPanel provides two primary API layers:

| API | Primary Use |
|-----|--------------|
| **UAPI** | Modern, JSON‑based, per‑user functions (`/json-api/cpanel`). |
| **XML‑API** | Legacy, still supported for compatibility (`/xml-api/...`). |

*UAPI Example: Retrieving a list of MySQL databases via `curl`*

```bash
curl -s -k -u "username:api_token" \
"https://yourserver.com:2083/execute/Mysql/list_databases?api.version=1"
```

*Response (JSON)*

```json
{
  "status": 1,
  "statusmsg": "OK",
  "data": [
    {"name": "shopdb"},
    {"name": "blogdb"},
    {"name": "testdb"}
  ]
}
```

**Generating API Tokens**: In **cPanel → Manage API Tokens**, create a token with the needed scopes (e.g., `Mail`, `MySQL`, `Domain`).

### Automation with Cron & Scripts

cPanel includes a **Cron Jobs** UI, but you can also manage cron entries directly in the user’s crontab (`crontab -e`). Combining cPanel CLI commands with cron enables automated maintenance.

*Example: Nightly cleanup of temporary files older than 30 days*

```bash
# Add to the user’s crontab (via cPanel → Cron Jobs)
0 2 * * * /usr/local/bin/find /home/username/tmp -type f -mtime +30 -delete
```

*Example: Auto‑renew Let's Encrypt certificates via CLI (if AutoSSL is disabled)*

```bash
# Run this script weekly via cron
/usr/local/cpanel/scripts/renewautossl --user=username
```

---

## Comparing cPanel with Alternative Control Panels

| Feature | cPanel | Plesk | DirectAdmin | Webmin/Virtualmin |
|---------|--------|-------|-------------|-------------------|
| **OS Support** | RHEL‑compatible (CentOS/AlmaLinux) | RHEL & Debian | RHEL & Debian | Debian/Ubuntu (Webmin) |
| **GUI** | Modern, icon‑driven | Tabbed, Windows‑like | Simpler, text‑heavy | Minimalist, mostly forms |
| **Reseller Support** | WHM built‑in | Plesk Panel with Reseller | DirectAdmin Admin | Virtualmin offers similar |
| **API** | UAPI (JSON) + XML‑API | REST + XML | XML‑API | REST (via plugins) |
| **Pricing** | Subscription per‑server | Subscription per‑server | One‑time license | Free (open source) |
| **App Installers** | Softaculous, Installatron | Installatron, Plesk Extensions | Softaculous (optional) | No native; manual |
| **Security** | CSF, ModSecurity, 2FA | Fail2Ban, ModSecurity | CSF optional | Configurable via modules |
| **Community** | Large, active forums + official docs | Strong, especially Windows hosting | Smaller but dedicated | Open‑source community |

**When to choose cPanel**: If you run a commercial hosting business that requires a polished UI for end‑users, integrated backup/restore, and a strong API ecosystem, cPanel remains the most feature‑rich and widely supported option.

**When alternatives may be better**: For budget‑constrained environments, non‑Linux OS (e.g., Windows Server), or when you prefer a lightweight interface, DirectAdmin or Webmin may be preferable.

---

## Best Practices for Security & Performance

1. **Apply the Principle of Least Privilege**
   - Use **Feature Lists** in WHM to restrict what each reseller or user can access (e.g., disable SSH access for shared accounts).

2. **Enforce Strong Password Policies**
   ```bash
   /usr/local/cpanel/bin/set_tweaksetting password_strength=strong
   ```

3. **Enable Two‑Factor Authentication (2FA)**
   - Recommended for **root**, **reseller**, and any privileged accounts.

4. **Regularly Update cPanel & System Packages**
   - Set **cPanel → Upgrade → Upgrade to Latest Version**.  
   - Use **yum/dnf** for OS updates: `yum update -y` (or `dnf` on newer releases).

5. **Optimize Apache/Nginx Settings**
   - Use **Service Configuration → Apache Configuration → Global Configuration** to enable **mod_deflate**, **mod_expires**, and adjust **MaxRequestWorkers** based on RAM.

6. **Leverage LiteSpeed or OpenLiteSpeed**
   - Install via **WHM → EasyApache 4** → select **LiteSpeed** for better concurrency and built‑in caching.

7. **Configure ModSecurity with OWASP CRS**
   ```bash
   /usr/local/cpanel/scripts/modsec_enable
   /usr/local/cpanel/scripts/modsec_update_rules
   ```

8. **Implement Resource Limits**
   - Set **cagefs** or **CloudLinux LVE** to prevent a single account from exhausting CPU or RAM.

9. **Automate Backups & Test Restores**
   - Schedule **incremental backups** to an off‑site S3 bucket.  
   - Quarterly, perform a **restore test** on a staging server.

10. **Monitor Logs & Alerts**
    - Enable **cPanel → Metrics → Log Watch** for real‑time error detection.  
    - Integrate with external services (e.g., **PagerDuty**, **Slack**) via **CSF** email alerts.

---

## Troubleshooting Common Issues

| Symptom | Likely Cause | Diagnostic Steps | Fix |
|---------|--------------|-------------------|-----|
| **“cPanel login failed – incorrect username/password”** | Account locked or password expired | 1. Check `/var/cpanel/logs/login_log` <br>2. Verify `pam_tally2` lockout count | Reset password via WHM → **Password Reset**; unlock with `pam_tally2 -u username -r` |
| **Email not sending (Exim errors)** | DNS/SPF misconfiguration or blocked port 25 | 1. Review `/var/log/exim_mainlog` <br>2. Run `exim -bt user@example.com` | Ensure proper **MX**, **SPF**, **DKIM** records; open port 25 in firewall |
| **“500 Internal Server Error” on a new PHP site** | Wrong PHP handler or missing modules | 1. Check Apache error log `/usr/local/apache/logs/error_log` <br>2. Verify PHP version via **Software → MultiPHP Manager** | Switch to a compatible PHP version; install missing extensions (`yum install php-mbstring`) |
| **Backups failing with “permission denied”** | Incorrect ownership of backup directory | 1. `ls -ld /home/username/backups/` <br>2. Look at `/var/log/cpbackup.log` | Set correct ownership: `chown username:username /home/username/backups/` |
| **cPanel UI extremely slow** | High CPU load or insufficient RAM | 1. Use **Metrics → CPU/Memory Usage** <br>2. Run `top` or `htop` on the server | Upgrade resources, enable **CloudLinux LVE**, or move to LiteSpeed |

---

## Migrating to / from cPanel

### Importing from Other Panels (e.g., Plesk)

cPanel offers a **Transfer Tool** under **WHM → Transfer Tool**:

1. **Source Server**: Enter IP/hostname, SSH port, and root credentials.  
2. **Select Accounts**: Choose which accounts to copy.  
3. **Package Mapping**: Align source packages to cPanel packages.  
4. **Run Transfer**: The tool copies home directories, databases (via `mysqldump`), and DNS zones.

**Post‑migration checklist**:

- Verify **DNS propagation** (especially if using external nameservers).  
- Re‑issue **SSL certificates** (AutoSSL will auto‑install if enabled).  
- Test **email flow** (SPF/DKIM may need regeneration).  

### Exporting from cPanel

cPanel provides **Backup Wizard** for full account export, or you can use the **cPanel API** to programmatically download data.

*Example: Download a full backup via API token*

```bash
curl -H "Authorization: cpanel username:API_TOKEN" \
"https://yourserver.com:2083/cpsess12345678/json-api/backup?api.version=1&user=username&type=full"
```

Once downloaded, the archive can be restored on another cPanel server using **WHM → Restore a Full Backup**.

---

## Pricing, Licensing, and Community Support

| License Tier | Accounts Limit | Monthly Cost (USD) | Typical Use‑Case |
|--------------|----------------|--------------------|------------------|
| **Solo** | ≤ 5 | $15 | Small business, single site |
| **Pro** | ≤ 30 | $30 | Reseller with few clients |
| **Premier** | Unlimited | $45+ (scale with servers) | Large hosting provider |
| **cPanel & WHM Cloud** | Per‑instance | $15–$30 (depending on VM size) | Cloud‑native deployments (AWS, DigitalOcean) |

**Support Channels**

- **Official Documentation** – <https://docs.cpanel.net/>  
- **cPanel Forums** – active community for troubleshooting.  
- **cPanel University** – paid courses for certification (e.g., **cPanel Administrator**).  
- **Third‑Party Blogs** – e.g., *LowEndTalk*, *WebHostTalk* for real‑world tips.  

---

## Future Trends & Emerging Features

1. **AI‑Driven Security Recommendations**  
   - cPanel 120 introduced an **AI Advisor** that analyses logs and suggests ModSecurity rule tweaks. Expect deeper integration with machine‑learning models for anomaly detection.

2. **Container‑Aware Backups**  
   - With the rise of Docker and Podman on hosting servers, cPanel is adding **container snapshot support** to its backup suite, allowing you to back up a whole LXC container alongside traditional data.

3. **Enhanced API Rate Limiting & OAuth2**  
   - Upcoming releases plan to replace API tokens with **OAuth2** scopes, improving security for third‑party integrations.

4. **Edge‑Caching Integration**  
   - Native hooks for CDN providers (Cloudflare, Fastly) to purge cache automatically after WordPress updates or file changes.

5. **Improved Multi‑PHP Management**  
   - **MultiPHP Manager** now supports per‑directory PHP version overrides via `.htaccess` automatically, simplifying complex legacy app stacks.

---

## Conclusion

cPanel remains a cornerstone of modern web hosting, blending an intuitive graphical interface with powerful command‑line and API capabilities. By mastering its core modules—domain management, email, databases, security, and backups—administrators can dramatically streamline daily operations. Moreover, the extensibility through CLI tools, UAPI, and third‑party plugins enables automation at scale, essential for any growing hosting business.

While alternatives exist, cPanel’s comprehensive feature set, mature ecosystem, and strong community support make it the go‑to solution for both shared‑hosting providers and dedicated server administrators. Implementing the security hardening steps, performance optimizations, and regular backup strategies discussed here will help you extract the maximum reliability and efficiency from your cPanel installation.

Whether you’re just starting your first website or running a multi‑tenant hosting platform, the principles, commands, and best practices outlined in this guide should serve as a solid foundation for safe, performant, and scalable web hosting with cPanel.

---

## Resources

- **cPanel Official Documentation** – Comprehensive guides, API references, and tutorials.  
  [https://docs.cpanel.net/](https://docs.cpanel.net/)

- **cPanel University – Certification Courses** – Structured learning paths for administrators and developers.  
  [https://university.cpanel.net/](https://university.cpanel.net/)

- **WHM/cPanel API Reference (UAPI & XML‑API)** – Detailed endpoint specifications and usage examples.  
  [https://api.docs.cpanel.net/](https://api.docs.cpanel.net/)

- **ModSecurity Core Rule Set (CRS) Project** – Open‑source rule set used by cPanel for WAF protection.  
  [https://coreruleset.org/](https://coreruleset.org/)

- **CloudLinux & LVE** – Resource isolation solutions often paired with cPanel for shared‑hosting environments.  
  [https://www.cloudlinux.com/](https://www.cloudlinux.com/)

- **Softaculous – One‑Click Installer** – Popular application installer integrated with cPanel.  
  [https://www.softaculous.com/](https://www.softaculous.com/)