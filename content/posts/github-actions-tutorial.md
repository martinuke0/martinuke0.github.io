---
title: "GitHub Actions: From Zero to Hero - A Complete Tutorial"
date: 2025-11-27T13:38:00+02:00
draft: false
tags: ["GitHub Actions", "CI/CD", "DevOps", "Automation", "Tutorial"]
categories: ["Development"]
---

# GitHub Actions: From Zero to Hero

GitHub Actions is like having a robot assistant that automatically does tasks for you whenever something happens in your GitHub repository. This tutorial will take you from complete beginner to advanced user, putting you ahead of 90% of developers.

## Table of Contents
1. [What is GitHub Actions? (ELI5)](#what-is-github-actions-eli5)
2. [Core Concepts](#core-concepts)
3. [Your First Workflow](#your-first-workflow)
4. [Intermediate Techniques](#intermediate-techniques)
5. [Advanced Patterns](#advanced-patterns)
6. [Real-World Examples](#real-world-examples)
7. [Pro Tips & Best Practices](#pro-tips--best-practices)
8. [Useful Resources](#useful-resources)

---

## What is GitHub Actions? (ELI5)

Imagine you have a lemonade stand. Every time you make lemonade, you need to:
1. Squeeze lemons
2. Add sugar
3. Mix with water
4. Taste test
5. Pour into cups

**GitHub Actions is like hiring a robot** that automatically does steps 2-4 every time you finish step 1. In programming terms:

- **Event** = You push code to GitHub
- **Workflow** = The recipe (steps to follow)
- **Actions** = Individual tasks (test code, deploy website, send notifications)

---

## Core Concepts

### 1. **Workflows**
A YAML file (`.github/workflows/name.yml`) that defines when and what to run.

### 2. **Events** (Triggers)
What starts your workflow:
- `push` - Code is pushed
- `pull_request` - PR is opened/updated
- `schedule` - Run on a timer (like cron)
- `workflow_dispatch` - Manual trigger
- `release` - New release is created

### 3. **Jobs**
A set of steps that run on the same machine. Jobs run in parallel by default.

### 4. **Steps**
Individual tasks within a job (run commands, use actions).

### 5. **Runners**
The computer that runs your workflow (GitHub-hosted or self-hosted).

---

## Your First Workflow

Let's create a simple workflow that runs tests when you push code.

**File:** `.github/workflows/test.yml`

```yaml
name: Run Tests

# When to run
on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

# What to run
jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
      # Step 1: Get your code
      - name: Checkout code
        uses: actions/checkout@v4
      
      # Step 2: Setup Node.js
      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'
      
      # Step 3: Install dependencies
      - name: Install dependencies
        run: npm install
      
      # Step 4: Run tests
      - name: Run tests
        run: npm test
```

**What's happening:**
1. Triggers on push/PR to `main` branch
2. Uses Ubuntu machine
3. Checks out your code
4. Installs Node.js 20
5. Installs npm packages
6. Runs your tests

---

## Intermediate Techniques

### 1. **Matrix Builds** (Test Multiple Versions)

Test your code on multiple Node.js versions simultaneously:

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        node-version: [16, 18, 20]
    
    steps:
      - uses: actions/checkout@v4
      - name: Use Node.js ${{ matrix.node-version }}
        uses: actions/setup-node@v4
        with:
          node-version: ${{ matrix.node-version }}
      - run: npm install
      - run: npm test
```

This creates **3 parallel jobs** - one for each Node version!

### 2. **Environment Variables & Secrets**

```yaml
jobs:
  deploy:
    runs-on: ubuntu-latest
    env:
      DATABASE_URL: ${{ secrets.DATABASE_URL }}
      API_KEY: ${{ secrets.API_KEY }}
    
    steps:
      - uses: actions/checkout@v4
      - name: Deploy
        run: |
          echo "Deploying to production..."
          ./deploy.sh
```

**Add secrets:** Repository Settings → Secrets and variables → Actions → New repository secret

### 3. **Conditional Steps**

```yaml
steps:
  - name: Deploy to production
    if: github.ref == 'refs/heads/main'
    run: ./deploy-prod.sh
  
  - name: Deploy to staging
    if: github.ref == 'refs/heads/develop'
    run: ./deploy-staging.sh
```

### 4. **Caching Dependencies**

Speed up workflows by caching node_modules:

```yaml
steps:
  - uses: actions/checkout@v4
  
  - name: Cache node modules
    uses: actions/cache@v3
    with:
      path: ~/.npm
      key: ${{ runner.os }}-node-${{ hashFiles('**/package-lock.json') }}
      restore-keys: |
        ${{ runner.os }}-node-
  
  - run: npm install
  - run: npm test
```

---

## Advanced Patterns

### 1. **Reusable Workflows**

Create a workflow that other workflows can call:

**File:** `.github/workflows/reusable-deploy.yml`
```yaml
name: Reusable Deploy

on:
  workflow_call:
    inputs:
      environment:
        required: true
        type: string
    secrets:
      deploy-token:
        required: true

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Deploy to ${{ inputs.environment }}
        run: ./deploy.sh ${{ inputs.environment }}
        env:
          TOKEN: ${{ secrets.deploy-token }}
```

**Use it:**
```yaml
jobs:
  deploy-staging:
    uses: ./.github/workflows/reusable-deploy.yml
    with:
      environment: staging
    secrets:
      deploy-token: ${{ secrets.STAGING_TOKEN }}
```

### 2. **Composite Actions** (Custom Actions)

Create your own reusable action:

**File:** `.github/actions/setup-project/action.yml`
```yaml
name: 'Setup Project'
description: 'Setup Node.js and install dependencies'

inputs:
  node-version:
    description: 'Node.js version'
    required: false
    default: '20'

runs:
  using: 'composite'
  steps:
    - uses: actions/setup-node@v4
      with:
        node-version: ${{ inputs.node-version }}
    
    - name: Install dependencies
      run: npm ci
      shell: bash
    
    - name: Build
      run: npm run build
      shell: bash
```

**Use it:**
```yaml
steps:
  - uses: actions/checkout@v4
  - uses: ./.github/actions/setup-project
    with:
      node-version: '18'
```

### 3. **Dynamic Matrix**

Generate matrix values dynamically:

```yaml
jobs:
  setup:
    runs-on: ubuntu-latest
    outputs:
      matrix: ${{ steps.set-matrix.outputs.matrix }}
    steps:
      - id: set-matrix
        run: |
          echo "matrix={\"include\":[{\"project\":\"web\"},{\"project\":\"api\"}]}" >> $GITHUB_OUTPUT
  
  build:
    needs: setup
    strategy:
      matrix: ${{ fromJson(needs.setup.outputs.matrix) }}
    runs-on: ubuntu-latest
    steps:
      - run: echo "Building ${{ matrix.project }}"
```

### 4. **Artifacts & Outputs**

Share data between jobs:

```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm run build
      
      - name: Upload build artifacts
        uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/
  
  deploy:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - name: Download artifacts
        uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/
      
      - run: ./deploy.sh
```

---

## Real-World Examples

### Example 1: Complete CI/CD Pipeline

```yaml
name: CI/CD Pipeline

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - run: npm ci
      - run: npm run lint
  
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        node-version: [18, 20]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: ${{ matrix.node-version }}
      - run: npm ci
      - run: npm test
      - name: Upload coverage
        uses: codecov/codecov-action@v3
  
  build:
    needs: [lint, test]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - run: npm ci
      - run: npm run build
      - uses: actions/upload-artifact@v4
        with:
          name: build
          path: dist/
  
  deploy:
    needs: build
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: build
          path: dist/
      - name: Deploy to production
        run: |
          echo "Deploying to production..."
          # Your deployment script here
```

### Example 2: Automated Releases

```yaml
name: Release

on:
  push:
    tags:
      - 'v*'

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Build
        run: |
          npm ci
          npm run build
      
      - name: Create Release
        uses: actions/create-release@v1
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        with:
          tag_name: ${{ github.ref }}
          release_name: Release ${{ github.ref }}
          draft: false
          prerelease: false
      
      - name: Publish to npm
        run: npm publish
        env:
          NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}
```

### Example 3: Scheduled Tasks

```yaml
name: Daily Cleanup

on:
  schedule:
    # Run at 2 AM UTC every day
    - cron: '0 2 * * *'
  workflow_dispatch: # Allow manual trigger

jobs:
  cleanup:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Clean old logs
        run: |
          find ./logs -type f -mtime +30 -delete
      
      - name: Commit changes
        run: |
          git config user.name "GitHub Actions"
          git config user.email "actions@github.com"
          git add .
          git commit -m "Automated cleanup" || echo "No changes"
          git push
```

---

## Pro Tips & Best Practices

### 1. **Use `workflow_dispatch` for Manual Triggers**

Always add this to test workflows manually:

```yaml
on:
  push:
    branches: [ main ]
  workflow_dispatch: # Add this!
```

### 2. **Pin Action Versions**

❌ **Bad:**
```yaml
- uses: actions/checkout@v4
```

✅ **Good:**
```yaml
- uses: actions/checkout@v4.1.1
```

### 3. **Use Concurrency to Cancel Old Runs**

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

### 4. **Fail Fast vs. Fail Safe**

```yaml
strategy:
  fail-fast: false # Continue other jobs even if one fails
  matrix:
    os: [ubuntu-latest, windows-latest, macos-latest]
```

### 5. **Use GitHub CLI in Workflows**

```yaml
- name: Create issue
  run: |
    gh issue create \
      --title "Build failed" \
      --body "Build failed on commit ${{ github.sha }}"
  env:
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

### 6. **Debugging Workflows**

```yaml
- name: Debug
  run: |
    echo "Event: ${{ github.event_name }}"
    echo "Ref: ${{ github.ref }}"
    echo "SHA: ${{ github.sha }}"
    echo "Actor: ${{ github.actor }}"
```

Enable debug logging: Repository Settings → Secrets → Add `ACTIONS_STEP_DEBUG` = `true`

### 7. **Optimize Workflow Speed**

- Use caching for dependencies
- Run jobs in parallel
- Use `ubuntu-latest` (fastest runner)
- Minimize checkout depth: `fetch-depth: 1`

### 8. **Security Best Practices**

- Never hardcode secrets
- Use `GITHUB_TOKEN` when possible
- Limit permissions:

```yaml
permissions:
  contents: read
  pull-requests: write
```

---

## Useful Resources

### Official Documentation
- [GitHub Actions Documentation](https://docs.github.com/en/actions) - Official docs
- [Workflow Syntax](https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions) - Complete YAML reference
- [GitHub Actions Marketplace](https://github.com/marketplace?type=actions) - Pre-built actions

### Learning Resources
- [GitHub Actions by Example](https://www.actionsbyexample.com/) - Practical examples
- [GitHub Skills](https://skills.github.com/) - Interactive tutorials
- [Awesome Actions](https://github.com/sdras/awesome-actions) - Curated list of actions

### Tools
- [act](https://github.com/nektos/act) - Run GitHub Actions locally
- [actionlint](https://github.com/rhysd/actionlint) - Lint your workflows
- [GitHub Actions VSCode Extension](https://marketplace.visualstudio.com/items?itemName=GitHub.vscode-github-actions) - Syntax highlighting & validation

### Community
- [GitHub Community Forum](https://github.community/c/code-to-cloud/github-actions/41) - Ask questions
- [r/github](https://www.reddit.com/r/github/) - Reddit community

---

## Conclusion

You now know:
- ✅ What GitHub Actions is and why it's powerful
- ✅ How to create basic workflows
- ✅ Intermediate techniques (matrix, caching, secrets)
- ✅ Advanced patterns (reusable workflows, composite actions)
- ✅ Real-world CI/CD pipelines
- ✅ Pro tips and best practices

**You're now ahead of 90% of GitHub users!** 🚀

Start small, experiment, and gradually build more complex workflows. The key is to automate repetitive tasks and let GitHub Actions do the heavy lifting.

---

**What's your first automation going to be?** Drop a comment below!
