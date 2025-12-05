---
title: "Build Your Next SaaS with Expo: Zero-to-Hero In‑Depth Guide"
date: "2025-12-05T13:20:17.89"
draft: false
tags: ["Expo", "React Native", "SaaS", "Mobile Development", "Payments", "Guide"]
---

## Introduction

Building a SaaS today means delivering a seamless experience across platforms, iterating quickly, and instrumenting everything from auth to analytics. Expo—on top of React Native—gives you a modern toolchain to ship high-quality mobile (and web) apps faster, with over-the-air updates, a file-based router, first-class TypeScript, deep integrations, and a sane path to the App Store and Google Play.

In this guide, you’ll go from zero to hero building a production-ready SaaS with Expo. We’ll cover architecture, auth, multi-tenancy, payments (Stripe and RevenueCat), deep linking, push notifications, OTA updates with EAS, testing, security, analytics, and CI/CD. You’ll get practical code snippets and a curated resources section for deeper research.

> Note: The Expo ecosystem evolves quickly. Always consult the latest Expo SDK and library docs before finalizing implementation details.

---

## Table of Contents

- Why Expo for SaaS
- Reference Architecture for an Expo-Powered SaaS
- Project Setup and Tooling
- Navigation and Screens with Expo Router
- Authentication and Multi‑Tenancy
- Data Layer: Queries, Caching, and State
- UI, Theming, Forms, and Validation
- Payments and Subscriptions (Stripe, RevenueCat)
- Push Notifications
- Deep Linking and Universal Links
- OTA Updates, Build, and Release with EAS
- Testing: Unit, Integration, and E2E
- Performance, Security, and Compliance
- Analytics and Monitoring
- Web Support and Monorepos
- DevOps, Secrets, and Environments
- Common Pitfalls and a Practical Roadmap
- Conclusion
- Resources for Further Research

---

## Why Expo for SaaS

- Speed to market: Rapid prototyping with Expo Go or a custom development build, plus over-the-air (OTA) updates for instant bugfixes.
- Cross-platform reach: Ship iOS, Android, and (optionally) Web from a single codebase with React Native Web.
- Modern DX: TypeScript by default, Expo Router (file-based routing), rich CLI, EAS Build/Submit/Update, and excellent first-party modules.
- Ecosystem: Mature integrations for auth (Supabase, Auth0, Clerk, Cognito), data (TanStack Query), payments (Stripe, RevenueCat), error tracking (Sentry), analytics (Amplitude, PostHog), and more.
- Scale-ready: Support for custom native modules via development builds, E2E testing tools, CI/CD with EAS, and structured configuration for environments.

---

## Reference Architecture for an Expo-Powered SaaS

A typical SaaS stack using Expo might look like:

- Client app: Expo + React Native + Expo Router (mobile-first; optional React Native Web for desktop-class web)
- Backend: 
  - Option A: Supabase (Postgres + Auth + Storage + Realtime)
  - Option B: Firebase (Auth + Firestore + Storage)
  - Option C: Appwrite/Hasura/AWS Amplify or a custom Node/Go/Rust backend
- Payments:
  - Stripe Billing (web-hosted checkout/portal) for B2B or where permitted by store policy
  - RevenueCat for native in-app subscriptions (IAP) on iOS/Android
- Data layer: TanStack Query for server-state, Zustand/Redux for UI state
- Notifications: Expo Notifications (with Expo Push Service) or direct APNs/FCM
- Analytics/Monitoring: Sentry, Amplitude/PostHog/Segment
- DevOps: EAS Build/Submit/Update, GitHub Actions, environment-specific configs
- Security: Secure credential storage, HTTPS APIs, data partitioning for multi-tenancy

> Note: Payment flows must comply with App Store/Play policies. When in doubt, review platform guidelines and consider a dual approach (IAP via RevenueCat + external billing for web/B2B).

---

## Project Setup and Tooling

Initialize your app with TypeScript and Expo Router:

```bash
# Create a new Expo app with router
npx create-expo-app@latest my-saas --template
# When prompted, select a TypeScript + Router template if available
# Or add router manually later:
# npm i expo-router react-native-safe-area-context react-native-screens

cd my-saas
npm install
npx expo start
```

Add core utilities:

```bash
# Data fetching & validation
npm i @tanstack/react-query zod react-hook-form
# State and UI
npm i zustand
# Networking, storage, utilities
npm i axios
npx expo install expo-secure-store expo-application
# Auth/backend example (Supabase)
npm i @supabase/supabase-js
# Notifications
npx expo install expo-notifications
# Sentry (monitoring)
npm i sentry-expo
```

Recommended project files:

- app.config.ts for environment-aware config
- src/lib for api clients and utilities
- src/features for domain modules (auth, billing, projects, etc.)
- src/components for shared UI
- src/providers for global context (QueryClient, Theme)
- tests for unit/integration tests

---

## Navigation and Screens with Expo Router

Expo Router lets you structure screens via filesystem conventions.

Example structure:

```
app/
  _layout.tsx              # Root layout
  (auth)/
    sign-in.tsx
    sign-up.tsx
  (app)/
    _layout.tsx            # Protected area layout
    index.tsx              # Dashboard
    settings.tsx
    billing.tsx
```

Root layout with providers:

```tsx
// app/_layout.tsx
import { Stack } from "expo-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect } from "react";
import * as Sentry from "sentry-expo";

const queryClient = new QueryClient();

export default function RootLayout() {
  useEffect(() => {
    Sentry.init({
      dsn: process.env.EXPO_PUBLIC_SENTRY_DSN,
      enableInExpoDevelopment: true,
      debug: __DEV__,
    });
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <Stack screenOptions={{ headerShown: false }} />
    </QueryClientProvider>
  );
}
```

Protected routes pattern with a gate:

```tsx
// app/(app)/_layout.tsx
import { Stack, useRouter } from "expo-router";
import { useEffect } from "react";
import { useAuth } from "../../src/features/auth/useAuth";

export default function AppLayout() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) router.replace("/(auth)/sign-in");
  }, [loading, user]);

  if (loading) return null;
  return <Stack screenOptions={{ headerShown: false }} />;
}
```

---

## Authentication and Multi‑Tenancy

You have many options; here’s a practical Supabase example that works well for B2B SaaS, plus guidance for other providers.

Initialize Supabase:

```ts
// src/lib/supabase.ts
import { createClient } from "@supabase/supabase-js";

export const supabase = createClient(
  process.env.EXPO_PUBLIC_SUPABASE_URL!,
  process.env.EXPO_PUBLIC_SUPABASE_ANON_KEY!,
  {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: false,
    },
  }
);
```

Auth hook:

```ts
// src/features/auth/useAuth.ts
import { useEffect, useState } from "react";
import { supabase } from "../../lib/supabase";

export function useAuth() {
  const [user, setUser] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => {
      setUser(data.user ?? null);
      setLoading(false);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user ?? null);
    });
    return () => sub.subscription.unsubscribe();
  }, []);

  return { user, loading };
}
```

Sign-in screen example:

```tsx
// app/(auth)/sign-in.tsx
import { useState } from "react";
import { View, TextInput, Button, Text, Alert } from "react-native";
import { supabase } from "../../src/lib/supabase";
import { router } from "expo-router";

export default function SignIn() {
  const [email, setEmail] = useState("");
  const [pwd, setPwd] = useState("");

  const signIn = async () => {
    const { error } = await supabase.auth.signInWithPassword({ email, password: pwd });
    if (error) Alert.alert("Error", error.message);
    else router.replace("/(app)");
  };

  return (
    <View style={{ padding: 16 }}>
      <Text>Email</Text>
      <TextInput value={email} onChangeText={setEmail} autoCapitalize="none" />
      <Text>Password</Text>
      <TextInput value={pwd} onChangeText={setPwd} secureTextEntry />
      <Button title="Sign In" onPress={signIn} />
    </View>
  );
}
```

Multi-tenancy strategies:

- Single database, tenant_id column on all rows. Enforce row-level security (RLS) by tenant.
- Separate schemas or databases per tenant for strong isolation.
- Use roles (owner, admin, member) and claims/jwt for authorization.

> For Supabase, enable RLS and write policies based on auth.uid() and tenant membership. For Auth0/Clerk/Cognito, include tenant claims in the token and enforce on your backend.

Alternatives:
- Auth0/Clerk: Great for passwordless/social auth, enterprise SSO, and session management.
- Firebase Auth: Simple mobile-first workflows.
- Cognito: AWS-native, better fit if you’re in AWS.

---

## Data Layer: Queries, Caching, and State

Use TanStack Query for server state and background sync:

```tsx
// src/lib/query.ts
import { QueryClient } from "@tanstack/react-query";
export const queryClient = new QueryClient();
```

Fetching utilities:

```ts
// src/lib/api.ts
import axios from "axios";

export const api = axios.create({
  baseURL: process.env.EXPO_PUBLIC_API_URL,
  timeout: 10000,
});

// Example interceptor for auth header
api.interceptors.request.use(async (config) => {
  // attach token if needed
  return config;
});
```

Query example:

```tsx
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";

export function useProjects() {
  return useQuery({
    queryKey: ["projects"],
    queryFn: async () => {
      const { data } = await api.get("/projects");
      return data;
    },
    staleTime: 60_000,
  });
}
```

UI state can live in Zustand or React Context:

```ts
import { create } from "zustand";

type UIState = { theme: "light" | "dark"; setTheme: (t: UIState["theme"]) => void };
export const useUI = create<UIState>((set) => ({
  theme: "light",
  setTheme: (theme) => set({ theme }),
}));
```

Offline-first considerations:
- Use query persistence (e.g., react-query-persist-client) + MMKV/AsyncStorage.
- Design conflict resolution if offline edits matter.

---

## UI, Theming, Forms, and Validation

- Theming: Use React Native Paper, Tamagui, or nativewind for theming and design systems.
- Forms: react-hook-form + zod for type-safe validation.

Example form:

```tsx
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";

const schema = z.object({
  name: z.string().min(2),
  email: z.string().email(),
});

type FormData = z.infer<typeof schema>;

export function ProfileForm() {
  const { register, handleSubmit, setValue, formState: { errors } } = useForm<FormData>({
    resolver: zodResolver(schema),
  });

  const onSubmit = (values: FormData) => {/* call API */};

  return (
    <>
      {/* Example wiring in RN */}
      {/* Use Controller for complex inputs */}
    </>
  );
}
```

Accessibility:
- Use accessible roles/labels (accessibilityLabel, accessible).
- Ensure color contrast and focus order.
- Test with screen readers on iOS and Android.

---

## Payments and Subscriptions (Stripe, RevenueCat)

You’ll likely need both strategies:

1) Stripe Billing (web-hosted) for B2B and cross-platform parity:
- Create checkout sessions on your backend.
- Launch Stripe-hosted Checkout or Billing Portal in-app via the browser.

```ts
// src/features/billing/stripe.ts
import * as WebBrowser from "expo-web-browser";
import { api } from "../../lib/api";

export async function openStripeCheckout() {
  const { data } = await api.post("/billing/checkout-session", { priceId: "price_..." });
  await WebBrowser.openBrowserAsync(data.url);
}

export async function openBillingPortal() {
  const { data } = await api.post("/billing/portal-session");
  await WebBrowser.openBrowserAsync(data.url);
}
```

2) Native IAP via RevenueCat for App Store/Play subscriptions:
- Offload product setup, receipt validation, and entitlements to RevenueCat.
- Use it if you sell digital content/features directly in-app.

```ts
// pseudo-code
import Purchases from "react-native-purchases";

export async function initRevenueCat() {
  await Purchases.configure({ apiKey: process.env.EXPO_PUBLIC_RC_API_KEY! });
}

export async function subscribe() {
  const offerings = await Purchases.getOfferings();
  const pkg = offerings.current?.availablePackages[0];
  if (pkg) {
    const { customerInfo } = await Purchases.purchasePackage(pkg);
    const active = customerInfo.entitlements.active["pro"];
    // unlock features if active
  }
}
```

> Compliance note:
> - Apple requires in-app purchases for selling digital goods in-app to consumers, with limited exceptions (e.g., “reader apps” or approved external link entitlement).
> - For B2B SaaS with external contracts, a login-only app may be acceptable. Always review App Store/Play policies for your specific scenario.

---

## Push Notifications

Install and configure:

```bash
npx expo install expo-notifications
```

Request permissions and get a push token:

```ts
// src/features/notifications/register.ts
import * as Notifications from "expo-notifications";
import * as Device from "expo-device";

export async function registerForPushNotificationsAsync() {
  if (!Device.isDevice) return null;

  const { status: existingStatus } = await Notifications.getPermissionsAsync();
  const finalStatus =
    existingStatus === "granted"
      ? "granted"
      : (await Notifications.requestPermissionsAsync()).status;

  if (finalStatus !== "granted") return null;

  const token = (await Notifications.getExpoPushTokenAsync({
    projectId: process.env.EXPO_PUBLIC_EAS_PROJECT_ID,
  })).data;

  // Send token to your backend
  return token;
}
```

Configure notification handling:

```ts
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true, shouldPlaySound: false, shouldSetBadge: false
  }),
});
```

Server-side, send via Expo’s Push API or through FCM/APNs directly.

---

## Deep Linking and Universal Links

Add a custom scheme and domains in app config:

```ts
// app.config.ts
export default ({ config }) => ({
  ...config,
  scheme: "mysaas",
  extra: {
    eas: { projectId: process.env.EXPO_PUBLIC_EAS_PROJECT_ID },
  },
  ios: {
    ...config.ios,
    bundleIdentifier: "com.example.mysaas",
    associatedDomains: ["applinks:app.example.com"],
  },
  android: {
    ...config.android,
    package: "com.example.mysaas",
    intentFilters: [
      {
        action: "VIEW",
        data: [{ scheme: "https", host: "app.example.com" }],
        category: ["BROWSABLE", "DEFAULT"],
      },
    ],
  },
});
```

Handle links with Expo Router automatically, e.g., opening mysass://billing routes or https://app.example.com/billing.

---

## OTA Updates, Build, and Release with EAS

Install and log in:

```bash
npm i -g eas-cli
eas login
eas init
```

Build:

```bash
eas build --platform ios
eas build --platform android
```

Submit to stores:

```bash
eas submit --platform ios
eas submit --platform android
```

Over-the-air updates (EAS Update):

```bash
# Configure updates in app.config.ts via runtimeVersion/channel if needed
eas update --branch production --message "Fix billing screen crash"
```

> OTA updates can’t change native code or entitlements. For native module changes, ship a new binary via EAS Build.

Development builds for custom native modules:

```bash
eas build --profile development --platform ios
# install on device/simulator then:
npx expo start --dev-client
```

---

## Testing: Unit, Integration, and E2E

- Unit/integration: Jest + React Native Testing Library
- E2E: Detox or Maestro
- API contracts: zod or TypeScript DTOs, with contract tests if using tRPC/GraphQL

Example Jest setup:

```bash
npm i -D jest @testing-library/react-native @types/jest jest-expo
```

Basic test:

```ts
import { render } from "@testing-library/react-native";
import SignIn from "../../app/(auth)/sign-in";

test("renders sign in", () => {
  const { getByText } = render(<SignIn />);
  expect(getByText("Email")).toBeTruthy();
});
```

Maestro example flow (high-level):

```yaml
# .maestro/sign-in.yml
appId: com.example.mysaas
---
- launchApp
- tapOn: "Email"
- inputText: "user@example.com"
- tapOn: "Password"
- inputText: "password"
- tapOn: "Sign In"
- assertVisible: "Dashboard"
```

---

## Performance, Security, and Compliance

Performance:
- Use FlatList/SectionList with proper keys and getItemLayout.
- Memoize components, use React Profiler, and avoid unnecessary re-renders.
- Lazy-load routes with Expo Router, code-split features, and prefetch queries.

Security:
- Store tokens in SecureStore, not AsyncStorage.
- Use HTTPS and short-lived tokens; refresh via backend.
- Enforce tenant isolation at the backend (RLS, ACLs).
- Don’t hardcode secrets in the app; use env variables and server-side logic.

Compliance:
- Respect privacy: App Tracking Transparency (iOS) if applicable.
- Data residency/GDPR: Provide data export/deletion, consent flows.
- Accessibility: Meet WCAG where feasible.

---

## Analytics and Monitoring

- Sentry for crashes and performance tracing:
  - Add sentry-expo plugin in app config and initialize in root.
- Product analytics: Amplitude/PostHog/Segment:
  - Track key events (onboarding completed, project created, plan upgraded).
  - Use screen tracking via router hooks.

Example Sentry plugin:

```json
{
  "expo": {
    "plugins": ["sentry-expo"]
  }
}
```

---

## Web Support and Monorepos

If you need a marketing site, docs, or a full web app:

- React Native Web: Reuse components to support web in the same Expo project.
- Or run a monorepo:
  - apps/mobile: Expo
  - apps/web: Next.js
  - packages/ui: shared design system
  - packages/utils: shared TS libraries

Tools: Turborepo or Nx to share code and optimize builds.

---

## DevOps, Secrets, and Environments

Environment management:
- Use app.config.ts with EXPO_PUBLIC_ variables for client-safe config.
- Keep server secrets server-side only.
- EAS Secrets for build-time variables:

```bash
eas secret:create --name EXPO_PUBLIC_SUPABASE_URL --value https://...
eas secret:create --name EXPO_PUBLIC_SUPABASE_ANON_KEY --value ...
```

GitHub Actions example:

```yaml
name: EAS Build
on:
  push:
    branches: [main]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: expo/expo-github-action@v8
        with:
          eas-version: latest
          token: ${{ secrets.EXPO_TOKEN }}
      - run: npm ci
      - run: eas build --platform all --non-interactive
```

---

## Common Pitfalls and a Practical Roadmap

Pitfalls:
- Forgetting App Store policy nuances for subscriptions. Decide IAP vs external billing early.
- Mixing server and client secrets. Never ship server secrets in the app.
- Overusing global state. Keep server data in TanStack Query, UI state in light stores.
- Skipping testing and monitoring. Add them from day one.

Suggested roadmap:
1) Week 1: Project scaffolding, router, theming, auth prototype.
2) Week 2: Core domain models, queries, caching, basic billing path (Stripe web).
3) Week 3: Notifications, deep links, analytics, error tracking.
4) Week 4: Hardening (a11y, i18n, security), testing, EAS release and OTA setup.
5) Week 5+: IAP via RevenueCat (if needed), performance, enterprise SSO, web support, admin tools.

---

## Conclusion

Expo is a powerful foundation for a modern SaaS: you can deliver native experiences on iOS and Android (and optionally web) from one codebase, ship fast with OTA updates, integrate best-in-class auth and payments, and operate confidently with testing, analytics, and CI/CD. By combining Expo Router, TanStack Query, Supabase/Auth0/Clerk, Stripe/RevenueCat, and EAS, you’ll have a production-grade stack that scales as your product grows.

Start small with a clean architecture and iterate. Keep platform policies and security in mind, instrument everything, and automate your releases. Your next SaaS can be both delightful and durable—with Expo.

---

## Resources for Further Research

Official docs and guides:
- Expo documentation: https://docs.expo.dev
- Expo Router: https://docs.expo.dev/router/introduction
- EAS Build/Submit/Update: https://docs.expo.dev/eas
- Expo Notifications: https://docs.expo.dev/versions/latest/sdk/notifications
- Sentry + Expo: https://docs.expo.dev/guides/using-sentry

Auth and backend:
- Supabase: https://supabase.com/docs
- Auth0 React Native: https://auth0.com/docs/quickstart/native/react-native
- Clerk React Native: https://clerk.com/docs/references/react-native
- Firebase Auth: https://firebase.google.com/docs/auth

Data and state:
- TanStack Query: https://tanstack.com/query/latest
- Zustand: https://docs.pmnd.rs/zustand/getting-started/introduction

Payments:
- Stripe Billing: https://stripe.com/docs/billing
- Stripe Checkout: https://stripe.com/docs/payments/checkout
- RevenueCat: https://www.revenuecat.com/docs

Testing:
- React Native Testing Library: https://testing-library.com/docs/react-native-testing-library/intro
- Jest Expo: https://docs.expo.dev/guides/testing-with-jest
- Detox: https://wix.github.io/Detox
- Maestro: https://maestro.mobile.dev

Web and monorepo:
- React Native Web: https://necolas.github.io/react-native-web
- Turborepo: https://turbo.build/repo

Policies and compliance:
- Apple App Review Guidelines: https://developer.apple.com/app-store/review/guidelines
- Google Play Policy Center: https://support.google.com/googleplay/android-developer/answer/9934569

Happy building!