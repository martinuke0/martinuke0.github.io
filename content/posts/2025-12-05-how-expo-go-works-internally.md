---
title: "How Expo Go Works Internally"
date: "2025-12-05T21:10:34.17"
draft: false
tags: ["expo", "react-native", "mobile-development", "javascript", "tutorial", "devtools"]
---

## Introduction

Expo Go is a cornerstone tool in the React Native ecosystem, enabling developers to build, test, and iterate on mobile apps rapidly without the overhead of compiling native code for every change. This tutorial dives deeply into **how Expo Go works internally**, revealing the architecture, workflows, and limitations that make it such a unique and powerful tool for mobile app development.

By understanding Expo Go’s inner workings, you will better leverage its capabilities, troubleshoot issues, and know when to transition to custom development builds.

---

## Table of Contents

- [What is Expo Go?](#what-is-expo-go)
- [Architecture of Expo Go](#architecture-of-expo-go)
- [How Expo Go Loads and Runs Your App](#how-expo-go-loads-and-runs-your-app)
- [The Role of Expo SDK and Native Modules](#the-role-of-expo-sdk-and-native-modules)
- [Code Reloading and Development Workflow](#code-reloading-and-development-workflow)
- [Limitations of Expo Go and When to Use Development Builds](#limitations-of-expo-go-and-when-to-use-development-builds)
- [Expo Go and the New React Native Architecture](#expo-go-and-the-new-react-native-architecture)
- [Conclusion](#conclusion)

---

## What is Expo Go?

Expo Go is a mobile application available on iOS and Android that acts as a **sandbox environment** for running React Native projects built with the Expo framework. Instead of building a standalone native app for every code change, developers install Expo Go and then load their JavaScript bundle over the network via a development server.

This allows **instant preview and hot reloading** of your React Native app on a real device or emulator without a full native build cycle. Expo Go includes a pre-packaged set of native modules, making it easy to use many popular APIs out of the box[5][7].

---

## Architecture of Expo Go

Internally, Expo Go is a **pre-built native container app** that bundles:

- A **React Native runtime** (JavaScriptCore or Hermes engine)
- A curated **Expo SDK** that exposes native functionality (camera, file system, sensors, SQLite, etc.)
- A **development server client** that connects to your local machine or a tunnel to fetch JavaScript bundles
- A **bridge system** enabling communication between JavaScript and native code

The key architectural idea is that Expo Go provides a **universal native shell** capable of running any JavaScript React Native app that uses only the native modules included in the Expo SDK[1][5].

---

## How Expo Go Loads and Runs Your App

1. **Starting the Dev Server:** When you run `expo start` in your project, Expo CLI spins up a Metro bundler server that watches your JavaScript files and generates a JavaScript bundle.

2. **Connecting the Device:** You launch Expo Go on your iOS or Android device and scan a QR code or use a tunnel URL. Expo Go connects to the dev server over the network.

3. **Fetching the Bundle:** Expo Go downloads the JavaScript bundle from the server.

4. **Running the Bundle:** The bundle is executed inside the embedded JavaScript engine (Hermes or JSC). React Native renders the UI by bridging JavaScript commands to native UI components already compiled into Expo Go.

5. **Hot Reloading:** When you save changes, the Metro bundler pushes an updated bundle. Expo Go applies the changes live without a full reload, speeding up development[7].

This process means your app code is **JavaScript only** and runs inside the Expo Go container, leveraging the native modules it includes.

---

## The Role of Expo SDK and Native Modules

Expo Go comes with a **fixed set of native modules** compiled into the app, collectively known as the **Expo SDK**. These modules provide access to device hardware and OS services such as:

- Camera, Location, Sensors
- FileSystem, SQLite database (using a bundled custom SQLite version for consistency)
- Network, Permissions
- Media playback and recording

Because Expo Go is a **universal app**, it cannot load arbitrary native code dynamically. This means if your project requires native modules not included in the Expo SDK, you cannot run it inside Expo Go directly[1][5][7].

If custom native code is needed, Expo provides **Development Builds** — custom-built versions of Expo Go with your native modules included. Development builds allow you to test native code changes while still benefiting from Expo’s fast refresh and other tooling[2].

---

## Code Reloading and Development Workflow

Expo Go supports several developer productivity features:

- **Fast Refresh:** Automatically reloads the app or updates components when you save changes.
- **Live Reload:** Reloads the entire app when a file changes.
- **Error Reporting:** Displays syntax and runtime errors inline.
- **Tunnel/Local Network:** Allows devices to connect to the development server even across different networks through Expo’s tunneling services.

This setup allows developers to iterate rapidly without waiting for native recompilation, making Expo Go ideal for prototyping and iterative development[7][8].

---

## Limitations of Expo Go and When to Use Development Builds

While Expo Go provides a smooth, fast development experience, it has **limitations**:

| Aspect                    | Expo Go                         | Development Builds                                  |
|---------------------------|--------------------------------|----------------------------------------------------|
| Custom Native Code        | **Not supported**               | Supported — you can include custom native modules  |
| Native Module Set         | Fixed, pre-included modules     | Fully customizable native code                      |
| Build Process             | No native build needed          | Requires native build via EAS Build or local build |
| App Store Submission      | Not for production release      | Supports standalone builds for app submission      |

When your app requires features outside the Expo SDK, or if you want to test native code, you switch to **Development Builds** — custom Expo Go-like apps with your native modules embedded[2][5].

---

## Expo Go and the New React Native Architecture

React Native’s **New Architecture**, featuring a revamped bridge, JSI (JavaScript Interface), and Fabric UI renderer, is now supported in Expo SDK 53 and later. Expo Go supports this new architecture, providing faster and more efficient communication between native and JavaScript layers.

Developers can enable or disable the new architecture in Expo projects, but Expo Go always runs with it enabled. This modernizes performance and compatibility for apps running inside Expo Go[4].

---

## Conclusion

Expo Go is a powerful, pre-built native app that acts as a **universal runtime for React Native projects**, enabling fast JavaScript development without native builds. Its internal architecture combines a React Native runtime and a curated Expo SDK of native modules, connected via a development server to deliver instant updates and hot reloading.

Understanding Expo Go’s architecture helps developers maximize its utility and recognize when to move to custom development builds for custom native code. With support for the new React Native architecture, Expo Go remains a vital tool for rapid mobile app development.

---

If you want to dive deeper, consider exploring **Expo Development Builds** and **EAS Build**, which extend Expo Go’s capabilities for more complex native development scenarios.

---

*This tutorial synthesizes information from official Expo documentation, community expertise, and recent presentations to provide a comprehensive internal view of Expo Go.*