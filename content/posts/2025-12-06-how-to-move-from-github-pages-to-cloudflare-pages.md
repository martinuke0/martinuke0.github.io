---
title: "How to Move from GitHub Pages to Cloudflare Pages"
date: "2025-12-06T11:54:19.23"
draft: false
tags: ["Cloudflare Pages", "GitHub Pages", "Static Sites", "Migration", "DevOps"]
---

## Introduction

GitHub Pages is a fantastic starting point for static sites. But as your needs grow—zero-downtime deploys, branch previews, global edge performance, custom headers and redirects, or serverless functions—you might want to graduate to Cloudflare Pages.

In this step-by-step guide, you’ll learn how to migrate cleanly from GitHub Pages to Cloudflare Pages with minimal or zero downtime, while preserving SEO, URLs, and performance. We’ll cover:

- Preparing your repository (Jekyll/Hugo/Eleventy/Next/Astro/etc.)
- Configuring Cloudflare Pages builds and environments
- Switching DNS with no downtime
- Preserving links via redirects and canonical URLs
- Handling SPA routing, caching, headers, and forms
- Rollbacks, previews, and common pitfalls

If you follow along, you can ship your site on Cloudflare Pages the same day.

## Table of Contents

- [Introduction](#introduction)
- [1) Decide What You’re Migrating](#1-decide-what-youre-migrating)
- [2) Prepare Your Repository](#2-prepare-your-repository)
  - [Jekyll specifics (ex-GitHub Pages defaults)](#jekyll-specifics-ex-github-pages-defaults)
  - [Other static generators](#other-static-generators)
- [3) Create Your Cloudflare Pages Project](#3-create-your-cloudflare-pages-project)
  - [Build commands and output directories](#build-commands-and-output-directories)
  - [Environment variables and versions](#environment-variables-and-versions)
- [4) Preview and QA Before DNS Cutover](#4-preview-and-qa-before-dns-cutover)
- [5) DNS and Custom Domains (No-Downtime Cutover)](#5-dns-and-custom-domains-no-downtime-cutover)
  - [If you already use a custom domain](#if-you-already-use-a-custom-domain)
  - [If you currently use usernamegithubio](#if-you-currently-use-usernamegithubio)
- [6) Preserve URLs, Redirects, and SEO](#6-preserve-urls-redirects-and-seo)
  - [Redirect rules](#redirect-rules)
  - [Canonical links and sitemaps](#canonical-links-and-sitemaps)
- [7) Headers, Caching, and Performance](#7-headers-caching-and-performance)
- [8) SPA Routing and Rewrites](#8-spa-routing-and-rewrites)
- [9) Forms and Dynamic Features](#9-forms-and-dynamic-features)
- [10) CI/CD, Previews, and Rollbacks](#10-cicd-previews-and-rollbacks)
- [Troubleshooting Common Issues](#troubleshooting-common-issues)
- [Example: Jekyll on GitHub Pages → Cloudflare Pages](#example-jekyll-on-github-pages--cloudflare-pages)
- [Alternative: If You Meant Salesforce Marketing Cloud “CloudPages”](#alternative-if-you-meant-salesforce-marketing-cloud-cloudpages)
- [Conclusion](#conclusion)

## 1) Decide What You’re Migrating

Start by inventorying your current site:

- Generator: Plain HTML/CSS, Jekyll (common on GitHub Pages), Hugo, Eleventy, Astro, Next.js (static export or SSR), SvelteKit, etc.
- Build output directory: e.g., `_site` (Jekyll), `public`, `dist`, `.next`, etc.
- URL structure and redirects: trailing slashes, legacy paths, old blog URLs.
- Custom domain: Do you use a custom domain (e.g., www.example.com) or the default `username.github.io`?
- Special needs: Forms, search, protected content, serverless functions, CMS webhooks.

Knowing these details informs your build configuration and DNS plan.

## 2) Prepare Your Repository

GitHub Pages can serve:
- Content directly from the repo (e.g., `/docs` directory or `gh-pages` branch), sometimes with Jekyll auto-builds, or
- Prebuilt static files pushed to a branch.

For Cloudflare Pages, you can:
- Build from source in the cloud (recommended), or
- Deploy prebuilt artifacts.

Make sure your repo builds locally first.

### Jekyll specifics (ex-GitHub Pages defaults)

If you relied on GitHub Pages’ built-in Jekyll:

1) Add a Gemfile so Pages can install dependencies:

```ruby
# Gemfile
source "https://rubygems.org"

gem "jekyll", "~> 4.3.3"
gem "webrick", "~> 1.8" # for local serve on Ruby 3.x
# Add other plugins you use:
# gem "jekyll-seo-tag"
# gem "jekyll-sitemap"
```

2) Lock your Ruby version (optional but recommended):

```
# .ruby-version
3.2.2
```

3) Ensure a standard Jekyll structure with `_config.yml` and content. If you previously depended on GitHub Pages’ restricted plugins, add those plugins explicitly to your Gemfile and `_config.yml`.

4) Test locally:

```bash
bundle install
bundle exec jekyll build   # outputs to ./_site
```

If you used `baseurl` on GitHub Pages (e.g., `baseurl: /my-repo`), consider setting it to `""` if moving to a root domain. Update asset paths to be absolute or relative accordingly.

> Tip: If you had a `.nojekyll` file to disable Jekyll on GitHub Pages, that’s fine to keep or remove—it won’t affect Cloudflare Pages.

### Other static generators

- Hugo: ensure a working `hugo` build locally; note your output dir (default `public`).
- Eleventy: `npx @11ty/eleventy` build; output often `_site` by default.
- Astro: `npx astro build`; output `dist`.
- Next.js: for static export use `next export` with `out` folder; for SSR/edge runtime, Cloudflare Pages can run via Pages Functions automatically with the correct adapter (framework presets handle this).
- SvelteKit/Nuxt/SolidStart/etc.: use their Cloudflare or static adapters; framework presets in Cloudflare handle most.

## 3) Create Your Cloudflare Pages Project

1) In the Cloudflare dashboard, go to Pages → Create a project.
2) Connect your GitHub account and select the repository.
3) Choose your build settings (framework preset where available).

### Build commands and output directories

Examples:

- Jekyll:
  - Build command: `bundle install && bundle exec jekyll build`
  - Output directory: `_site`

- Hugo:
  - Build command: `hugo --minify`
  - Output directory: `public`

- Eleventy:
  - Build command: `npm ci && npx @11ty/eleventy`
  - Output directory: `_site`

- Astro:
  - Build command: `npm ci && npm run build`
  - Output directory: `dist`

- Next.js (static export):
  - Build command: `npm ci && npm run build && npx next export`
  - Output directory: `out`

- Next.js (SSR on Pages Functions):
  - Choose the Next.js preset; Cloudflare will configure functions automatically. Output dir is handled by the preset.

> Important: Ensure the “Output directory” matches what your generator produces. If Cloudflare doesn’t find it, the deployment will be empty.

### Environment variables and versions

Set versions to match your local environment when needed:

- Node:
  - In package.json:
    ```json
    {
      "engines": { "node": "20.x" }
    }
    ```
  - Or set an environment variable like `NODE_VERSION=20`.

- Ruby (for Jekyll):
  - Add `.ruby-version` and/or set `RUBY_VERSION=3.2.2`.

- Hugo:
  - Set `HUGO_VERSION=0.133.0` (example) if you want a specific version in the builder.

- Custom variables:
  - Add API keys or tokens as environment variables in Pages → Settings → Environment variables.
  - Use “Preview” vs “Production” environments to scope secrets.

## 4) Preview and QA Before DNS Cutover

Every push triggers a build at a unique `*.pages.dev` URL. Use this to:

- Click through critical pages, forms, and interactive components.
- Validate images, fonts, and asset URLs (especially if you changed `baseurl`).
- Test 404/500 pages and SPA routing.
- Check mobile and performance with Lighthouse.
- Confirm redirects and headers (see sections below).

Only move DNS once you’re satisfied.

## 5) DNS and Custom Domains (No-Downtime Cutover)

### If you already use a custom domain

1) Lower TTL ahead of time  
   Reduce the TTL on your existing DNS records (e.g., to 300 seconds) a few hours before the cutover to speed propagation.

2) Add the domain in Cloudflare Pages  
   In your Pages project → Custom domains → Add a domain. Cloudflare will:
   - If your DNS is on Cloudflare: suggest and apply the correct CNAME records and provision TLS automatically.
   - If your DNS is elsewhere: instruct you to create a CNAME pointing `www` to `<project>.pages.dev`. For apex domain (`example.com`), if your DNS provider doesn’t support CNAME flattening, consider moving DNS to Cloudflare or use an ALIAS/ANAME if supported.

3) Validate and roll  
   Once verification passes and the certificate is active, traffic will serve from Cloudflare’s edge. Keep your GitHub Pages site untouched until you fully verify production.

4) No-downtime check  
   Because you validated on a preview URL first, the DNS change should be seamless. If needed, perform the cut during a low-traffic window and monitor.

### If you currently use username.github.io

- You can’t configure a server-side 301 from `username.github.io` to your new domain. Instead:
  - Prefer moving to a custom domain (recommended for brand and SEO control).
  - Replace the content at `username.github.io` with a lightweight HTML page that uses a `<meta http-equiv="refresh">` and a canonical link to hint search engines, or keep it as a separate property.

Example redirect page:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Moved</title>
  <link rel="canonical" href="https://www.example.com/">
  <meta http-equiv="refresh" content="0; url=https://www.example.com/">
</head>
<body>
  <p>This site has moved to <a href="https://www.example.com/">https://www.example.com/</a>.</p>
</body>
</html>
```

## 6) Preserve URLs, Redirects, and SEO

### Redirect rules

Cloudflare Pages supports a `_redirects` file at the project root (or your output directory). Use it to maintain old GitHub Pages URLs:

```
# 301 redirect a page
/old-post.html   /blog/old-post/   301

# Redirect entire sections
/docs/*          /guides/:splat    301

# Force www
https://example.com/*  https://www.example.com/:splat  301

# SPA fallback (rewrite, not redirect)
# See SPA section for a 200 rewrite version
```

Place `_redirects` alongside your built assets so it’s deployed with the site.

### Canonical links and sitemaps

- Add `<link rel="canonical" href="https://www.example.com/current-url/">` in your templates.
- Make sure `sitemap.xml` reflects your new domain.
- Keep `robots.txt` updated.

> Tip: If you changed trailing slash behavior, set consistent redirects to avoid duplicate content.

## 7) Headers, Caching, and Performance

Use a `_headers` file to set HTTP headers per path:

```
/*
  Cache-Control: public, max-age=600
  Strict-Transport-Security: max-age=31536000; includeSubDomains; preload
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
  Referrer-Policy: no-referrer-when-downgrade
  Permissions-Policy: geolocation=(), microphone=()

/assets/*
  Cache-Control: public, max-age=31536000, immutable

/service-worker.js
  Cache-Control: no-cache
```

- For fingerprinted assets (e.g., app.a1b2c3.js), set `immutable` with a long `max-age`.
- For HTML, prefer a short TTL for rapid updates.
- Cloudflare serves your content from its global edge, improving TTFB for users worldwide.

## 8) SPA Routing and Rewrites

For single-page apps where unknown paths should serve `index.html`, add a rewrite entry in `_redirects`:

```
# Serve index.html for all non-file routes (200 rewrite)
/*   /index.html   200
```

Place this as the last rule so other redirects take precedence.

If you’re using a framework preset (e.g., React, Vue, Svelte), Cloudflare often configures this automatically; still, it’s safe to be explicit.

## 9) Forms and Dynamic Features

GitHub Pages is static-only; Cloudflare Pages adds optional serverless functions (Pages Functions powered by Cloudflare Workers).

- Create a `functions/` directory at your repo root to add endpoints.
- Example: a simple JSON echo for form submissions:

```ts
// functions/api/contact.ts
export const onRequestPost: PagesFunction = async ({ request }) => {
  const data = await request.json().catch(() => ({}));
  // TODO: validate, write to KV/D1/R2, or forward to a webhook
  return new Response(JSON.stringify({ ok: true, received: data }), {
    headers: { "Content-Type": "application/json" },
  });
};
```

Then POST to `/api/contact` from your form. You can integrate with:
- Cloudflare KV/D1/R2 for storage
- Email APIs (Mailgun/Sendgrid/Postmark)
- Turnstile for CAPTCHA

Remember to secure endpoints (e.g., CSRF tokens, origin checks, or server-side validation).

## 10) CI/CD, Previews, and Rollbacks

- Every commit to your production branch creates a new deployment; pull requests generate immutable preview URLs.
- Environment-specific variables: configure “Preview” vs “Production” secrets.
- If a release misbehaves, roll back by promoting a previous deployment in the Pages dashboard—no code revert required.
- You can also use Branch Deployments for staging environments.

> Tip: Protect your main branch and use PR previews for QA to avoid regressions in production.

## Troubleshooting Common Issues

- Empty deployments: The output directory doesn’t match. Fix the build command or output path.
- Broken asset paths after migration: Revisit `baseurl` (Jekyll) or use absolute paths. Consider `<base href="/">` for static exports.
- 404s for SPA deep links: Add the SPA rewrite rule in `_redirects`.
- Mixed content (HTTP assets on HTTPS pages): Update hardcoded `http://` asset URLs to `https://` or protocol-relative `//`.
- Build timeouts or missing tools: Pin versions via environment variables or files. Add `npm ci`/`bundle install` to build commands.
- Custom domain not validating: Ensure DNS record points to `<project>.pages.dev` as instructed; wait for TLS certificate to issue (can take a few minutes).

## Example: Jekyll on GitHub Pages → Cloudflare Pages

1) Prepare:
   - Add Gemfile, `.ruby-version`, and ensure `bundle exec jekyll build` works locally.
   - Confirm `_config.yml` has `baseurl: ""` if moving to the domain root.

2) Connect to Cloudflare Pages:
   - Create project → Connect GitHub repo.
   - Build command: `bundle install && bundle exec jekyll build`
   - Output directory: `_site`
   - Set `RUBY_VERSION=3.2.2` (or your version) in environment variables.

3) Add redirects and headers (optional):
   - `_redirects` for old URLs.
   - `_headers` for security and caching.

4) Validate preview:
   - Visit the `*.pages.dev` preview deployment, check navigation, assets, and SEO tags.

5) Cut over DNS:
   - Pages → Custom domains → Add www and/or apex domain.
   - If DNS is on Cloudflare, allow it to create records automatically. Otherwise, create the CNAME it suggests.
   - Wait for TLS to provision and verify traffic.

6) Monitor and finalize:
   - Keep GitHub Pages content in place until you confirm a stable production on Cloudflare.
   - Update your sitemap in Search Console and monitor for crawl errors.

## Alternative: If You Meant Salesforce Marketing Cloud “CloudPages”

If your goal is to move a static site from GitHub Pages into Salesforce Marketing Cloud’s CloudPages:

- Export static HTML from your generator (`jekyll build`, `hugo`, `astro build`).
- In SFMC, use CloudPages to create a Collection and Landing Pages.
- Upload or paste your HTML/CSS/JS into CloudPages content blocks or use Code Resource pages.
- Rewrite relative asset paths or host assets on a CDN (SFMC doesn’t act as a general static host).
- For forms, leverage AMPScript/SSJS and DEs (Data Extensions) per SFMC best practices.
- Test in multiple business units and publish to the assigned CloudPages domain.
- Expect a different deployment model than CI-driven static hosts.

Because the platforms are very different, there’s no 1:1 migration—plan for reimplementation of dynamic pieces.

## Conclusion

Migrating from GitHub Pages to Cloudflare Pages is straightforward and unlocks powerful benefits: global edge speed, preview deployments, robust redirects and headers, and optional serverless functions—all while keeping your repo-centric workflow.

The safest path is:
- Validate builds locally,
- Stand up a Pages preview,
- Configure redirects, headers, and environment variables,
- Then perform a measured DNS cutover for zero downtime.

With careful attention to URL preservation, caching, and QA, your site will be faster, more flexible, and easier to evolve on Cloudflare Pages.