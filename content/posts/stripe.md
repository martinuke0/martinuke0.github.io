---
title: "The Complete Guide to Stripe Payments in JavaScript: From Beginner to Hero"
date: 2025-11-29T17:09:00+02:00
draft: false
tags: ["stripe", "payments", "javascript", "saas", "web-development", "nodejs"]
---

## Table of Contents
1. [Introduction: Why Stripe for Your SaaS](#introduction)
2. [Core Concepts: Understanding Payment Processing](#core-concepts)
3. [Setup: Getting Started](#setup)
4. [One-Time Payments: The Foundation](#one-time-payments)
5. [Subscriptions: The SaaS Backbone](#subscriptions)
6. [Webhooks: Listening to Stripe Events](#webhooks)
7. [Customer Management: Building Relationships](#customer-management)
8. [Security: Protecting Your Business](#security)
9. [Testing: Getting It Right](#testing)
10. [Production Checklist: Going Live](#production-checklist)
11. [Resources: Your Arsenal](#resources)

---

## Introduction: Why Stripe for Your SaaS {#introduction}

Stripe is the payment infrastructure that powers millions of businesses worldwide. For SaaS founders, it's the gold standard because:

- **Developer-First Design**: Beautiful APIs that make sense
- **Subscription Management**: Built-in recurring billing
- **Global Reach**: Supports 135+ currencies and dozens of payment methods
- **Reliability**: 99.999% uptime SLA
- **Compliance**: PCI DSS Level 1 certified (you don't handle card data)

**The Mental Model**: Think of Stripe as a smart payment router. Money flows from your customer → through Stripe (which handles all the complexity) → into your bank account. You never touch sensitive card data; you just tell Stripe what to charge and when.

---

## Core Concepts: Understanding Payment Processing {#core-concepts}

Before we write code, let's understand the key concepts. These will stick with you forever.

### 1. **The Customer Object**
Every person who pays you is a Customer in Stripe. This is a container that holds:
- Payment methods (credit cards, bank accounts)
- Subscription history
- Metadata (your user ID, email, etc.)

**Why it matters**: You create a Customer once, then charge them many times. This is crucial for SaaS.

### 2. **Payment Methods vs Payment Intents**
- **Payment Method**: A card, bank account, or other payment source
- **Payment Intent**: A single attempt to collect money

**The Flow**:
```
Customer adds card → Payment Method created → 
You create Payment Intent → Stripe charges card → Money moves
```

### 3. **Subscriptions: The SaaS Engine**
A Subscription automatically charges a Customer on a recurring schedule:
- Links a Customer to a Price
- Handles billing cycles automatically
- Manages upgrades/downgrades
- Sends invoices

**Key Insight**: You don't manually charge customers each month. The Subscription does it for you.

### 4. **Products and Prices**
- **Product**: What you're selling (e.g., "Pro Plan")
- **Price**: How much it costs and how often (e.g., "$29/month")

One Product can have multiple Prices (monthly, yearly, different currencies).

### 5. **Webhooks: The Event System**
Stripe sends you HTTP requests when things happen:
- Payment succeeds
- Subscription canceled
- Card expires

**Critical Understanding**: Never rely solely on your frontend. Webhooks are the source of truth because:
- Users can close their browser
- Networks can fail
- You need to know about automatic charges

---

## Setup: Getting Started {#setup}

### Step 1: Create Your Stripe Account

1. Go to [stripe.com](https://stripe.com) and sign up
2. Complete business verification (needed for payouts)
3. Navigate to **Developers** → **API Keys**

You'll see two key pairs:

**Test Mode** (for development):
- Publishable key: `pk_test_...` (safe to expose in frontend)
- Secret key: `sk_test_...` (NEVER expose, server-only)

**Live Mode** (for production):
- Publishable key: `pk_live_...`
- Secret key: `sk_live_...`

**Mental Model**: Publishable keys identify your account. Secret keys have full power to charge cards and must stay server-side.

### Step 2: Install Stripe Libraries
```bash
# Backend (Node.js)
npm install stripe

# Frontend (React/Vue/Vanilla JS)
npm install @stripe/stripe-js

# If using Express for webhooks
npm install express body-parser
```

### Step 3: Environment Variables

Create a `.env` file (NEVER commit this to Git):
```env
# Server-side only
STRIPE_SECRET_KEY=sk_test_your_secret_key_here
STRIPE_WEBHOOK_SECRET=whsec_your_webhook_secret_here

# Can be used client-side
STRIPE_PUBLISHABLE_KEY=pk_test_your_publishable_key_here
```

**Security Rule**: Secret keys live on your server. Publishable keys can go in your frontend.

---

## One-Time Payments: The Foundation {#one-time-payments}

Let's build a simple checkout flow. This is the foundation for everything else.

### The Two-Step Dance

**Step 1: Frontend** - Collect payment method securely  
**Step 2: Backend** - Create charge with your secret key

### Example: Simple Product Purchase

#### Frontend (HTML + Vanilla JS)
```
    // Initialize Stripe with your publishable key
    const stripe = Stripe('pk_test_YOUR_PUBLISHABLE_KEY');

    document.getElementById('checkout-button').addEventListener('click', async () => {
      // Call your backend to create a checkout session
      const response = await fetch('/create-checkout-session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ productId: 'coffee-mug' })
      });

      const session = await response.json();

      // Redirect to Stripe-hosted checkout page
      const result = await stripe.redirectToCheckout({
        sessionId: session.id
      });

      if (result.error) {
        alert(result.error.message);
      }
    });
  
```

**What's happening here?**
1. User clicks "Buy Now"
2. We ask our server to create a Checkout Session
3. Stripe provides a secure payment page
4. User enters card details on Stripe's domain (not yours - you never see card numbers)
5. After payment, Stripe redirects user back to your site

#### Backend (Node.js + Express)
```javascript
const express = require('express');
const stripe = require('stripe')(process.env.STRIPE_SECRET_KEY);

const app = express();
app.use(express.json());

// Create Checkout Session endpoint
app.post('/create-checkout-session', async (req, res) => {
  try {
    const session = await stripe.checkout.sessions.create({
      payment_method_types: ['card'],
      line_items: [
        {
          price_data: {
            currency: 'usd',
            product_data: {
              name: 'Premium Coffee Mug',
              images: ['https://example.com/mug.jpg'],
            },
            unit_amount: 2500, // Amount in cents ($25.00)
          },
          quantity: 1,
        },
      ],
      mode: 'payment', // One-time payment
      success_url: 'https://yoursite.com/success?session_id={CHECKOUT_SESSION_ID}',
      cancel_url: 'https://yoursite.com/canceled',
    });

    res.json({ id: session.id });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.listen(3000, () => console.log('Server running on port 3000'));
```

**Key Points:**
- `unit_amount` is in cents (2500 = $25.00)
- `mode: 'payment'` means one-time charge
- Stripe hosts the payment page (you redirect users there)
- `{CHECKOUT_SESSION_ID}` in success_url gets replaced by Stripe

### Alternative: Payment Intents (Custom UI)

If you want to build your own checkout form (more control, more complexity):

#### Frontend (React Example)
```jsx
import React, { useState } from 'react';
import { loadStripe } from '@stripe/stripe-js';
import { Elements, CardElement, useStripe, useElements } from '@stripe/react-stripe-js';

const stripePromise = loadStripe('pk_test_YOUR_PUBLISHABLE_KEY');

function CheckoutForm() {
  const stripe = useStripe();
  const elements = useElements();
  const [error, setError] = useState(null);
  const [processing, setProcessing] = useState(false);

  const handleSubmit = async (event) => {
    event.preventDefault();
    setProcessing(true);

    // Step 1: Create PaymentIntent on your server
    const response = await fetch('/create-payment-intent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ amount: 2500 }) // $25 in cents
    });

    const { clientSecret } = await response.json();

    // Step 2: Confirm payment with card details
    const result = await stripe.confirmCardPayment(clientSecret, {
      payment_method: {
        card: elements.getElement(CardElement),
        billing_details: { name: 'Customer Name' }
      }
    });

    if (result.error) {
      setError(result.error.message);
      setProcessing(false);
    } else {
      // Payment succeeded!
      console.log('Payment successful:', result.paymentIntent);
      setProcessing(false);
      // Redirect to success page
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <CardElement />
      <button type="submit" disabled={!stripe || processing}>
        {processing ? 'Processing...' : 'Pay $25'}
      </button>
      {error && <div style={{ color: 'red' }}>{error}</div>}
    </form>
  );
}

function App() {
  return (
    <Elements stripe={stripePromise}>
      <CheckoutForm />
    </Elements>
  );
}

export default App;
```

#### Backend (Payment Intent)
```javascript
app.post('/create-payment-intent', async (req, res) => {
  try {
    const { amount } = req.body;

    const paymentIntent = await stripe.paymentIntents.create({
      amount: amount,
      currency: 'usd',
      // Optional: save customer info
      metadata: { 
        userId: 'user_123',
        orderId: 'order_456'
      }
    });

    // Send client secret to frontend
    res.json({ clientSecret: paymentIntent.client_secret });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});
```

**When to use each approach:**
- **Checkout Sessions**: Faster to implement, Stripe handles UI, mobile-optimized
- **Payment Intents**: Full UI control, custom branding, embedded experience

---

## Subscriptions: The SaaS Backbone {#subscriptions}

This is where Stripe truly shines for SaaS. Subscriptions automate recurring billing.

### The Subscription Lifecycle
```
Customer created → Subscribe to Plan → 
  First charge → Monthly renewal → 
    Upgrade/Downgrade → Cancel
```

### Step 1: Create Products and Prices in Stripe Dashboard

Go to **Products** → **Add Product**:
```
Product: "Pro Plan"
  - Price: $29/month (price_abc123)
  - Price: $290/year (price_xyz789)

Product: "Enterprise Plan"
  - Price: $99/month (price_def456)
```

**Why create in dashboard first?** Prices are the foundation. You reference these IDs in your code.

### Step 2: Create Subscription Checkout

#### Frontend
```javascript
  const stripe = Stripe('pk_test_YOUR_KEY');

  document.getElementById('subscribe-button').addEventListener('click', async () => {
    const response = await fetch('/create-subscription-checkout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        priceId: 'price_abc123', // Your Pro monthly price ID
        userId: 'user_12345' // Your internal user ID
      })
    });

    const session = await response.json();
    await stripe.redirectToCheckout({ sessionId: session.id });
  });

```

#### Backend
```javascript
app.post('/create-subscription-checkout', async (req, res) => {
  const { priceId, userId } = req.body;

  try {
    // Step 1: Create or retrieve Stripe Customer
    let customer;
    
    // Check if user already has a Stripe customer ID in your database
    const existingCustomerId = await db.getUserStripeId(userId);
    
    if (existingCustomerId) {
      customer = await stripe.customers.retrieve(existingCustomerId);
    } else {
      // Create new customer
      const user = await db.getUser(userId);
      customer = await stripe.customers.create({
        email: user.email,
        metadata: { userId: userId }
      });
      
      // Save Stripe customer ID to your database
      await db.saveUserStripeId(userId, customer.id);
    }

    // Step 2: Create Checkout Session for subscription
    const session = await stripe.checkout.sessions.create({
      customer: customer.id,
      payment_method_types: ['card'],
      line_items: [
        {
          price: priceId, // Reference the price ID
          quantity: 1,
        },
      ],
      mode: 'subscription', // This is key - not 'payment'
      success_url: 'https://yoursite.com/success?session_id={CHECKOUT_SESSION_ID}',
      cancel_url: 'https://yoursite.com/pricing',
      
      // Optional: trial period
      subscription_data: {
        trial_period_days: 14,
        metadata: { userId: userId }
      }
    });

    res.json({ id: session.id });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});
```

**Critical Concepts:**

1. **`mode: 'subscription'`** - This tells Stripe to create recurring charges
2. **Customer object** - Always link subscriptions to a Customer (this is how Stripe knows who to charge)
3. **Price ID** - References the Product/Price you created in the dashboard
4. **Metadata** - Store your user ID here to link Stripe data back to your database

### Step 3: Handle Subscription Success

When a user completes checkout, you need to:
1. Verify the subscription was created
2. Grant access in your app
3. Save subscription details
```javascript
app.get('/success', async (req, res) => {
  const sessionId = req.query.session_id;

  try {
    // Retrieve the checkout session
    const session = await stripe.checkout.sessions.retrieve(sessionId);
    
    // Get the subscription
    const subscription = await stripe.subscriptions.retrieve(session.subscription);

    // Update your database
    const userId = subscription.metadata.userId;
    await db.updateUser(userId, {
      subscriptionId: subscription.id,
      subscriptionStatus: subscription.status, // 'active', 'trialing', etc.
      planName: 'Pro',
      currentPeriodEnd: new Date(subscription.current_period_end * 1000)
    });

    res.send('Welcome to Pro! Your subscription is active.');
  } catch (error) {
    res.status(500).send('Error processing subscription');
  }
});
```

### Step 4: Check Subscription Status

Before granting access to features, check if the user has an active subscription:
```javascript
async function hasActiveSubscription(userId) {
  const user = await db.getUser(userId);
  
  if (!user.subscriptionId) {
    return false;
  }

  // Verify with Stripe (in case subscription was canceled/failed)
  const subscription = await stripe.subscriptions.retrieve(user.subscriptionId);
  
  return ['active', 'trialing'].includes(subscription.status);
}

// Middleware example
app.get('/api/premium-feature', async (req, res) => {
  const userId = req.user.id; // From your auth system
  
  if (!await hasActiveSubscription(userId)) {
    return res.status(403).json({ error: 'Premium subscription required' });
  }

  // Grant access to premium feature
  res.json({ data: 'Premium content here' });
});
```

### Managing Subscriptions: The Customer Portal

Stripe provides a **Customer Portal** - a pre-built interface where customers can:
- View invoices
- Update payment method
- Cancel subscription
- Upgrade/downgrade plans

#### Enable Customer Portal

1. Go to Stripe Dashboard → **Settings** → **Billing** → **Customer Portal**
2. Configure what actions customers can take
3. Customize branding

#### Create Portal Session
```javascript
app.post('/create-portal-session', async (req, res) => {
  const { userId } = req.body;
  
  try {
    const user = await db.getUser(userId);
    const stripeCustomerId = user.stripeCustomerId;

    // Create portal session
    const session = await stripe.billingPortal.sessions.create({
      customer: stripeCustomerId,
      return_url: 'https://yoursite.com/account',
    });

    res.json({ url: session.url });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});
```

#### Frontend Button
```javascript

  document.getElementById('manage-subscription').addEventListener('click', async () => {
    const response = await fetch('/create-portal-session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ userId: currentUser.id })
    });

    const { url } = await response.json();
    window.location.href = url; // Redirect to portal
  });

```

**Why use the Portal?**
- Saves months of development
- PCI compliant (card updates)
- Automatic invoice generation
- Mobile-optimized

### Handling Upgrades and Downgrades

When a user switches plans, you want to charge them immediately (upgrade) or credit them (downgrade).
```javascript
app.post('/change-subscription', async (req, res) => {
  const { userId, newPriceId } = req.body;

  try {
    const user = await db.getUser(userId);
    const subscription = await stripe.subscriptions.retrieve(user.subscriptionId);

    // Update the subscription
    const updatedSubscription = await stripe.subscriptions.update(
      subscription.id,
      {
        items: [
          {
            id: subscription.items.data[0].id,
            price: newPriceId, // New plan price ID
          },
        ],
        proration_behavior: 'always_invoice', // Charge/credit immediately
      }
    );

    // Update your database
    await db.updateUser(userId, {
      planName: 'Enterprise', // Or whatever the new plan is
      subscriptionStatus: updatedSubscription.status
    });

    res.json({ success: true, subscription: updatedSubscription });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});
```

**Proration Explained:**
- User pays $29/mo for Pro
- 15 days into month, upgrades to $99/mo Enterprise
- Stripe calculates: 
  - Credit for unused Pro time: ~$14.50
  - Charge for remaining Enterprise time: ~$49.50
  - Net charge: ~$35
- User gets immediate access, fair pricing

### Canceling Subscriptions
```javascript
app.post('/cancel-subscription', async (req, res) => {
  const { userId, immediate } = req.body;

  try {
    const user = await db.getUser(userId);
    
    if (immediate) {
      // Cancel immediately (user loses access now)
      await stripe.subscriptions.cancel(user.subscriptionId);
      
      await db.updateUser(userId, {
        subscriptionStatus: 'canceled',
        planName: 'Free'
      });
    } else {
      // Cancel at period end (user keeps access until renewal date)
      await stripe.subscriptions.update(user.subscriptionId, {
        cancel_at_period_end: true
      });
      
      await db.updateUser(userId, {
        subscriptionStatus: 'canceling' // Custom status for your app
      });
    }

    res.json({ success: true });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});
```

**Best Practice:** Always cancel at period end (`cancel_at_period_end: true`). Users appreciate getting what they paid for.

---

## Webhooks: Listening to Stripe Events {#webhooks}

This is THE most important section for SaaS. Webhooks are how your app stays in sync with Stripe.

### Why Webhooks Are Critical

Imagine these scenarios:
1. User's card expires → Stripe fails to charge → Subscription goes past_due
2. User disputes a charge → You need to revoke access
3. User cancels via Customer Portal → Your app needs to know

**Without webhooks, you'd have no idea these happened.**

### The Webhook Flow
```
Something happens in Stripe → 
  Stripe sends HTTP POST to your webhook endpoint → 
    You verify it's from Stripe → 
      Update your database → 
        Send 200 OK response
```

### Step 1: Create Webhook Endpoint
```javascript
const express = require('express');
const stripe = require('stripe')(process.env.STRIPE_SECRET_KEY);

const app = express();

// IMPORTANT: Use raw body for webhooks (not JSON)
app.post('/webhook', 
  express.raw({ type: 'application/json' }), 
  async (req, res) => {
    const sig = req.headers['stripe-signature'];
    const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET;

    let event;

    try {
      // Verify webhook signature
      event = stripe.webhooks.constructEvent(req.body, sig, webhookSecret);
    } catch (err) {
      console.log(`Webhook signature verification failed:`, err.message);
      return res.status(400).send(`Webhook Error: ${err.message}`);
    }

    // Handle the event
    switch (event.type) {
      case 'checkout.session.completed':
        const session = event.data.object;
        await handleCheckoutComplete(session);
        break;

      case 'customer.subscription.created':
        const subscription = event.data.object;
        await handleSubscriptionCreated(subscription);
        break;

      case 'customer.subscription.updated':
        await handleSubscriptionUpdated(event.data.object);
        break;

      case 'customer.subscription.deleted':
        await handleSubscriptionDeleted(event.data.object);
        break;

      case 'invoice.payment_succeeded':
        await handlePaymentSucceeded(event.data.object);
        break;

      case 'invoice.payment_failed':
        await handlePaymentFailed(event.data.object);
        break;

      default:
        console.log(`Unhandled event type: ${event.type}`);
    }

    // Return 200 to acknowledge receipt
    res.json({ received: true });
  }
);

// For all other routes, use JSON parser
app.use(express.json());
```

**Critical Security Point:** The `stripe.webhooks.constructEvent()` call verifies the webhook came from Stripe. Without this, anyone could POST to your endpoint and mess with your data.

### Step 2: Get Your Webhook Secret

**For Development (using Stripe CLI):**
```bash
# Install Stripe CLI
# Mac: brew install stripe/stripe-cli/stripe
# Windows: Download from stripe.com/docs/stripe-cli

# Login
stripe login

# Forward webhooks to your local server
stripe listen --forward-to localhost:3000/webhook
```

This will output a webhook secret like `whsec_...` - add it to your `.env` file.

**For Production:**

1. Go to Stripe Dashboard → **Developers** → **Webhooks**
2. Click **Add Endpoint**
3. Enter your production URL: `https://yoursite.com/webhook`
4. Select events to listen for
5. Copy the signing secret

### Step 3: Handle Key Events

#### Subscription Created
```javascript
async function handleSubscriptionCreated(subscription) {
  const userId = subscription.metadata.userId;

  await db.updateUser(userId, {
    subscriptionId: subscription.id,
    subscriptionStatus: subscription.status,
    currentPeriodEnd: new Date(subscription.current_period_end * 1000),
    planName: 'Pro' // Determine from subscription.items.data[0].price.id
  });

  // Send welcome email
  await sendEmail(userId, 'Welcome to Pro!', '...');
}
```

#### Subscription Updated
```javascript
async function handleSubscriptionUpdated(subscription) {
  const userId = subscription.metadata.userId;

  await db.updateUser(userId, {
    subscriptionStatus: subscription.status,
    currentPeriodEnd: new Date(subscription.current_period_end * 1000),
    cancelAtPeriodEnd: subscription.cancel_at_period_end
  });

  // If subscription went from active to past_due
  if (subscription.status === 'past_due') {
    // Send payment reminder email
    await sendEmail(userId, 'Payment Failed', 'Please update your card...');
  }
}
```

#### Subscription Deleted (Canceled)
```javascript
async function handleSubscriptionDeleted(subscription) {
  const userId = subscription.metadata.userId;

  await db.updateUser(userId, {
    subscriptionId: null,
    subscriptionStatus: 'canceled',
    planName: 'Free'
  });

  // Send cancellation email
  await sendEmail(userId, 'Subscription Canceled', 'Sorry to see you go...');
}
```

#### Payment Failed
```javascript
async function handlePaymentFailed(invoice) {
  const subscription = await stripe.subscriptions.retrieve(invoice.subscription);
  const userId = subscription.metadata.userId;

  // Update user status
  await db.updateUser(userId, {
    subscriptionStatus: 'past_due'
  });

  // Send urgent email
  await sendEmail(userId, 'Payment Failed - Action Required', `
    We couldn't process your payment. Please update your card to avoid service interruption.
    Attempt ${invoice.attempt_count} of 4.
  `);

  // Optionally: Restrict access after X failed attempts
  if (invoice.attempt_count >= 3) {
    await db.updateUser(userId, { accessLimited: true });
  }
}
```

#### Payment Succeeded (Renewal)
```javascript
async function handlePaymentSucceeded(invoice) {
  // Only handle subscription invoices (not one-time payments)
  if (!invoice.subscription) return;

  const subscription = await stripe.subscriptions.retrieve(invoice.subscription);
  const userId = subscription.metadata.userId;

  await db.updateUser(userId, {
    subscriptionStatus: 'active',
    currentPeriodEnd: new Date(subscription.current_period_end * 1000),
    lastPaymentDate: new Date()
  });

  // Send receipt email
  await sendEmail(userId, 'Payment Received - Thank You!', `
    Your subscription has been renewed.
    Amount: $${(invoice.amount_paid / 100).toFixed(2)}
    Next billing date: ${new Date(subscription.current_period_end * 1000).toLocaleDateString()}
  `);
}
```

### Webhook Best Practices

1. **Always return 200 quickly**
```javascript
   // Do this:
   res.json({ received: true });
   await processWebhookAsync(event); // Background processing

   // Not this:
   await processWebhook(event); // Blocks response
   res.json({ received: true });
```

2. **Handle duplicate events** (Stripe may send the same event multiple times)
```javascript
   // Check if event already processed
   const processed = await db.getProcessedEvent(event.id);
   if (processed) {
     return res.json({ received: true }); // Already handled
   }

   // Process event
   await handleEvent(event);

   // Mark as processed
   await db.saveProcessedEvent(event.id);
```

3. **Log everything**
```javascript
   console.log(`Webhook received: ${event.type}`, {
     eventId: event.id,
     customerId: event.data.object.customer,
     timestamp: new Date()
   });
```

4. **Use metadata liberally**
```javascript
   // When creating subscriptions, always add metadata
   await stripe.subscriptions.create({
     customer: customerId,
     items: [{ price: priceId }],
     metadata: {
       userId: '12345',
       planType: 'pro',
       source: 'pricing_page'
     }
   });
```

---

## Customer Management: Building Relationships {#customer-management}

Managing customers well = higher retention = more revenue.

### Creating Customers with Full Details
```javascript
async function createStripeCustomer(user) {
  const customer = await stripe.customers.create({
    email: user.email,
    name: user.fullName,
    metadata: {
      userId: user.id,
      signupDate: new Date().toISOString()
    },
    // Optional: pre-fill address
    address: {
      line1: user.address,
      city: user.city,
      state: user.state,
      postal_code: user.zip,
      country: 'US'
    },
    // Optional: add tax IDs
    tax_id_data: user.vatNumber ? [{
      type: 'eu_vat',
      value: user.vatNumber
    }] : undefined
  });

  return customer;
}
```

### Searching for Customers
```javascript
// Find customer by email
const customers = await stripe.customers.list({
  email: 'user@example.com',
  limit: 1
});

// Find customers by metadata
const customers = await stripe.customers.search({
  query: `metadata['userId']:'12345'`
});

// List all customers with active subscriptions
const customers = await stripe.customers.list({
  limit: 100,
  expand: ['data.subscriptions']
});
```

### Attaching Payment Methods
```javascript
// After collecting payment method on frontend
const paymentMethod = await stripe.paymentMethods.attach(
  'pm_1234567890', // Payment method ID from frontend
  { customer: 'cus_ABC123' }
);

// Set as default payment method
await stripe.customers.update('cus_ABC123', {
  invoice_settings: {
    default_payment_method: paymentMethod.id
  }
});
```

### Updating Customer Information
```javascript
app.post('/update-customer-info', async (req, res) => {
  const { userId, email, name, address } = req.body;

  try {
    const user = await db.getUser(userId);
    
    await stripe.customers.update(user.stripeCustomerId, {
      email: email,
      name: name,
      address: address
    });

    res.json({ success: true });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});
```

### Viewing Customer Details
```javascript
async function getCustomerFullDetails(customerId) {
  // Get customer with expanded subscriptions and payment methods
  const customer = await stripe.customers.retrieve(customerId, {
    expand: [
      'subscriptions',
      'invoice_settings.default_payment_method',
      'tax_ids'
    ]
  });

  // Get payment history
  const charges = await stripe.charges.list({
    customer: customerId,
    limit: 10
  });

  // Get upcoming invoice (for active subscriptions)
  let upcomingInvoice = null;
  if (customer.subscriptions.data.length > 0) {
    try {
      upcomingInvoice = await stripe.invoices.retrieveUpcoming({
        customer: customerId
      });
    } catch (e) {
      // No upcoming invoice
    }
  }

  return {
    customer,
    charges: charges.data,
    upcomingInvoice,
    nextPaymentAmount: upcomingInvoice ? upcomingInvoice.amount_due / 100 : null,
    nextPaymentDate: upcomingInvoice ? new Date(upcomingInvoice.period_end * 1000) : null
  };
}
```

### Customer Lifetime Value (LTV)
```javascript
async function calculateCustomerLTV(customerId) {
  // Get all successful charges
  const charges = await stripe.charges.list({
    customer: customerId,
    limit: 100 // Adjust based on needs
  });

  const totalRevenue = charges.data
    .filter(charge => charge.paid && !charge.refunded)
    .reduce((sum, charge) => sum + charge.amount, 0);

  return totalRevenue / 100; // Convert cents to dollars
}
```

---

## Security: Protecting Your Business {#security}

Payment security is non-negotiable. Here's how to get it right.

### 1. Never Store Card Details

**❌ NEVER do this:**
```javascript
// DON'T EVER DO THIS
await db.saveUser({
  cardNumber: req.body.cardNumber, // NEVER
  cvv: req.body.cvv, // NEVER
  expiry: req.body.expiry // NEVER
});
```

**✅ Let Stripe handle it:**
```javascript
// Stripe stores the card, you store the reference
const paymentMethod = await stripe.paymentMethods.create({
  type: 'card',
  card: {
    token: tokenFromFrontend // Tokenized by Stripe.js
  }
});

await db.saveUser({
  stripePaymentMethodId: paymentMethod.id // Safe to store
});
```

### 2. Verify Webhook Signatures (Always!)
```javascript
// BAD - Anyone can POST to this
app.post('/webhook', async (req, res) => {
  const event = req.body; // Unverified!
  await processEvent(event); // Dangerous!
});

// GOOD - Verified webhook
app.post('/webhook', express.raw({ type: 'application/json' }), async (req, res) => {
  const sig = req.headers['stripe-signature'];
  
  try {
    const event = stripe.webhooks.constructEvent(
      req.body,
      sig,
      process.env.STRIPE_WEBHOOK_SECRET
    );
    await processEvent(event); // Safe!
  } catch (err) {
    return res.status(400).send(`Webhook Error: ${err.message}`);
  }
});
```

### 3. Use Idempotency Keys for Critical Operations

Prevents duplicate charges if network fails:
```javascript
const { v4: uuidv4 } = require('uuid');

// Generate unique idempotency key
const idempotencyKey = uuidv4();

await stripe.charges.create({
  amount: 2000,
  currency: 'usd',
  customer: customerId
}, {
  idempotencyKey: idempotencyKey // Same key = same result
});

// If this request fails and you retry with the same key,
// Stripe returns the original charge (no duplicate)
```

### 4. Validate Amounts Server-Side
```javascript
// BAD - Trusting client
app.post('/create-payment', async (req, res) => {
  const { amount } = req.body; // User could send any amount!
  await stripe.charges.create({ amount, currency: 'usd' });
});

// GOOD - Verify server-side
app.post('/create-payment', async (req, res) => {
  const { productId } = req.body;
  
  // Look up actual price in your database or config
  const product = await db.getProduct(productId);
  const amount = product.price; // Server determines price
  
  await stripe.charges.create({ 
    amount: amount, 
    currency: 'usd',
    metadata: { productId: productId }
  });
});
```

### 5. Environment Variables (Never Commit Keys)
```javascript
// .env file (add to .gitignore!)
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...

// Load with dotenv
require('dotenv').config();

const stripe = require('stripe')(process.env.STRIPE_SECRET_KEY);
```

### 6. Rate Limiting
```javascript
const rateLimit = require('express-rate-limit');

const paymentLimiter = rateLimit({
  windowMs: 15 * 60 * 1000, // 15 minutes
  max: 5, // Max 5 payment attempts
  message: 'Too many payment attempts, please try again later'
});

app.post('/create-payment', paymentLimiter, async (req, res) => {
  // Payment logic
});
```

### 7. HTTPS Only (In Production)
```javascript
// Redirect HTTP to HTTPS
app.use((req, res, next) => {
  if (req.header('x-forwarded-proto') !== 'https' && process.env.NODE_ENV === 'production') {
    res.redirect(`https://${req.header('host')}${req.url}`);
  } else {
    next();
  }
});
```

### 8. PCI Compliance Checklist

If you use Stripe Checkout or Elements (recommended), you're automatically PCI compliant because:
- Card data never touches your server
- Stripe handles all sensitive data
- You only store safe references (customer IDs, payment method IDs)

**Self-Assessment Questionnaire (SAQ A):**
- ✅ Use Stripe Checkout or Elements
- ✅ Serve your site over HTTPS
- ✅ Don't store card data
- ✅ Use Stripe.js from Stripe's servers (not self-hosted)

---

## Testing: Getting It Right {#testing}

Stripe provides test mode and test cards. Use them extensively before going live.

### Test Mode vs Live Mode

Every Stripe account has two modes:
- **Test Mode**: Fake money, for development
- **Live Mode**: Real money, for production

Switch between them in the dashboard (top left toggle).

### Test Card Numbers
```javascript
// Successful payment
4242 4242 4242 4242

// Requires authentication (3D Secure)
4000 0025 0000 3155

// Card declined
4000 0000 0000 9995

// Insufficient funds
4000 0000 0000 9995

// Expired card
4000 0000 0000 0069

// Processing error
4000 0000 0000 0119
```

**Expiry:** Any future date (e.g., 12/34)  
**CVV:** Any 3 digits (e.g., 123)  
**ZIP:** Any 5 digits (e.g., 12345)

### Testing Subscriptions
```javascript
// Create a test subscription that expires in 1 minute
const subscription = await stripe.subscriptions.create({
  customer: testCustomerId,
  items: [{ price: testPriceId }],
  trial_period_days: 0,
  billing_cycle_anchor: Math.floor(Date.now() / 1000) + 60 // 1 minute from now
});

// Wait 1 minute, then check for invoice.payment_succeeded webhook
```

### Testing Webhooks Locally
```bash
# Terminal 1: Run your server
npm start

# Terminal 2: Forward Stripe webhooks
stripe listen --forward-to localhost:3000/webhook

# Terminal 3: Trigger test events
stripe trigger payment_intent.succeeded
stripe trigger customer.subscription.deleted
stripe trigger invoice.payment_failed
```

### Automated Testing Example
```javascript
const stripe = require('stripe')(process.env.STRIPE_TEST_SECRET_KEY);

describe('Subscription Flow', () => {
  let testCustomer;

  beforeEach(async () => {
    // Create test customer
    testCustomer = await stripe.customers.create({
      email: 'test@example.com',
      payment_method: 'pm_card_visa', // Test payment method
      invoice_settings: {
        default_payment_method: 'pm_card_visa'
      }
    });
  });

  afterEach(async () => {
    // Clean up
    await stripe.customers.del(testCustomer.id);
  });

  it('should create subscription successfully', async () => {
    const subscription = await stripe.subscriptions.create({
      customer: testCustomer.id,
      items: [{ price: 'price_test_123' }]
    });

    expect(subscription.status).toBe('active');
    expect(subscription.items.data[0].price.id).toBe('price_test_123');
  });

  it('should handle failed payment', async () => {
    // Use test card that always declines
    const paymentMethod = await stripe.paymentMethods.create({
      type: 'card',
      card: { token: 'tok_chargeDeclined' }
    });

    await stripe.paymentMethods.attach(paymentMethod.id, {
      customer: testCustomer.id
    });

    const subscription = await stripe.subscriptions.create({
      customer: testCustomer.id,
      items: [{ price: 'price_test_123' }],
      default_payment_method: paymentMethod.id
    });

    // Subscription will be created but first payment fails
    expect(['incomplete', 'past_due']).toContain(subscription.status);
  });
});
```

### Manual Testing Checklist

Before going live, manually test:

- [ ] Successful payment
- [ ] Declined card
- [ ] 3D Secure authentication
- [ ] Subscription creation
- [ ] Subscription upgrade
- [ ] Subscription downgrade
- [ ] Subscription cancellation
- [ ] Failed renewal payment
- [ ] Successful renewal payment
- [ ] Customer Portal (update card, cancel)
- [ ] Webhook delivery (check logs)
- [ ] Webhook signature verification
- [ ] Refund processing
- [ ] Invoice generation

---

## Production Checklist: Going Live {#production-checklist}

### 1. Switch to Live Keys
```javascript
// .env.production
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PUBLISHABLE_KEY=pk_live_...
STRIPE_WEBHOOK_SECRET=whsec_... (from live webhook)
```

### 2. Complete Business Profile

In Stripe Dashboard → **Settings** → **Business Profile**:
- ✅ Business name
- ✅ Business address
- ✅ Customer support email/phone
- ✅ Statement descriptor (appears on credit card statements)
- ✅ Bank account (for payouts)

### 3. Enable Payment Methods

**Settings** → **Payment Methods**:
- ✅ Credit cards (Visa, Mastercard, Amex)
- ✅ Digital wallets (Apple Pay, Google Pay)
- ✅ Regional methods (iDEAL, SEPA, etc.) if serving those markets

### 4. Set Up Webhooks (Production)

1. Go to **Developers** → **Webhooks**
2. Add endpoint: `https://yoursite.com/webhook`
3. Select events:
   - `checkout.session.completed`
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.payment_succeeded`
   - `invoice.payment_failed`
   - `payment_intent.succeeded`
   - `payment_intent.payment_failed`
4. Copy signing secret to production `.env`

### 5. Configure Customer Portal

**Settings** → **Billing** → **Customer Portal**:
- ✅ Enable portal
- ✅ Allow customers to update payment method
- ✅ Allow customers to cancel subscription
- ✅ Set cancellation flow (survey, retention offer)
- ✅ Customize branding (logo, colors)

### 6. Set Up Email Receipts

**Settings** → **Emails**:
- ✅ Enable automatic receipts
- ✅ Customize email template
- ✅ Set "from" email address

### 7. Tax Configuration

**Settings** → **Tax**:
- ✅ Enable Stripe Tax (automatic tax calculation)
- ✅ Or configure tax rates manually
- ✅ Set up tax ID collection if needed

### 8. Radar (Fraud Prevention)

**Settings** → **Radar**:
- ✅ Enable Radar (included free)
- ✅ Review default rules
- ✅ Add custom rules if needed (e.g., block countries)

### 9. Monitoring & Alerts

Set up alerts for:
- Failed webhooks
- High decline rates
- Dispute received
- Subscription churn spike
```javascript
// Example: Slack alert for failed webhooks
app.post('/webhook', async (req, res) => {
  try {
    // Process webhook
  } catch (error) {
    // Send alert
    await fetch(process.env.SLACK_WEBHOOK_URL, {
      method: 'POST',
      body: JSON.stringify({
        text: `🚨 Webhook failed: ${error.message}`
      })
    });
  }
});
```

### 10. Logging
```javascript
const winston = require('winston');

const logger = winston.createLogger({
  level: 'info',
  format: winston.format.json(),
  transports: [
    new winston.transports.File({ filename: 'error.log', level: 'error' }),
    new winston.transports.File({ filename: 'combined.log' })
  ]
});

// Log all Stripe operations
app.post('/create-subscription', async (req, res) => {
  logger.info('Creating subscription', { 
    userId: req.user.id,
    priceId: req.body.priceId 
  });

  try {
    const subscription = await stripe.subscriptions.create({...});
    logger.info('Subscription created', { subscriptionId: subscription.id });
  } catch (error) {
    logger.error('Subscription creation failed', { error: error.message });
  }
});
```

### 11. Backup Webhook Endpoint

Set up a second webhook endpoint as backup:
Primary: https://yoursite.com/webhook
Backup: https://backup.yoursite.com/webhook

### 12. Documentation

Document your integration:
- Flow diagrams (checkout → webhook → database update)
- API endpoint documentation
- Webhook event handlers
- Testing procedures
- Rollback plan

### 13. Test in Production (Small Scale)

- Start with a few trusted beta users
- Monitor logs closely
- Verify webhooks are received
- Check that access grants/revokes work
- Confirm emails are sent

### 14. Set Up Monitoring Dashboard

Track these metrics:
- Monthly Recurring Revenue (MRR)
- Churn rate
- Failed payment rate
- Average subscription length
- Customer Lifetime Value (LTV)
```javascript
// Example: Daily MRR calculation
async function calculateMRR() {
  const subscriptions = await stripe.subscriptions.list({
    status: 'active',
    limit: 100,
    expand: ['data.plan']
  });

  let mrr = 0;
  for (const sub of subscriptions.data) {
    const amount = sub.items.data[0].price.unit_amount;
    const interval = sub.items.data[0].price.recurring.interval;
    
    // Normalize to monthly
    if (interval === 'month') {
      mrr += amount;
    } else if (interval === 'year') {
      mrr += amount / 12;
    }
  }

  return mrr / 100; // Convert cents to dollars
}
```

### 15. Legal Pages

Ensure you have:
- ✅ Terms of Service (mention auto-renewal, cancellation policy)
- ✅ Privacy Policy (mention Stripe as payment processor)
- ✅ Refund Policy

---

## Resources: Your Arsenal {#resources}

### Official Documentation
- **Stripe Docs**: https://stripe.com/docs
- **API Reference**: https://stripe.com/docs/api
- **Stripe CLI**: https://stripe.com/docs/stripe-cli
- **Webhooks Guide**: https://stripe.com/docs/webhooks
- **Testing Guide**: https://stripe.com/docs/testing

### Client Libraries
- **Node.js**: https://github.com/stripe/stripe-node
- **React (stripe-js)**: https://github.com/stripe/stripe-js
- **React Elements**: https://github.com/stripe/react-stripe-js

### Key Concepts Deep Dives
- **Payment Intents**: https://stripe.com/docs/payments/payment-intents
- **Subscriptions**: https://stripe.com/docs/billing/subscriptions/overview
- **Customer Portal**: https://stripe.com/docs/billing/subscriptions/customer-portal
- **SCA (3D Secure)**: https://stripe.com/docs/strong-customer-authentication
- **Proration**: https://stripe.com/docs/billing/subscriptions/prorations

### Tools
- **Stripe Dashboard**: https://dashboard.stripe.com
- **Stripe CLI**: https://stripe.com/docs/stripe-cli
- **Test Card Numbers**: https://stripe.com/docs/testing#cards
- **Webhook Tester**: Use Stripe CLI `stripe listen`

### Security
- **PCI Compliance**: https://stripe.com/docs/security/guide
- **Best Practices**: https://stripe.com/docs/security
- **Webhook Security**: https://stripe.com/docs/webhooks/signatures

### Advanced Topics
- **Connect (Marketplaces)**: https://stripe.com/docs/connect
- **Stripe Tax**: https://stripe.com/docs/tax
- **Radar (Fraud)**: https://stripe.com/docs/radar
- **Usage-Based Billing**: https://stripe.com/docs/billing/subscriptions/usage-based

### Community & Support
- **Stripe Discord**: https://discord.gg/stripe
- **Stack Overflow**: Tag `stripe-payments`
- **Stripe Support**: https://support.stripe.com
- **Status Page**: https://status.stripe.com

### Video Tutorials
- **Stripe YouTube Channel**: https://www.youtube.com/stripeinc
- **Web Dev Simplified - Stripe Tutorial**: Search YouTube

### Example Projects
- **Stripe Samples**: https://github.com/stripe-samples
- **SaaS Starter Kits**: 
  - https://github.com/stripe-samples/subscription-use-cases
  - https://github.com/vercel/nextjs-subscription-payments

### Books & Courses
- **"Stripe Integration Guide"** (various authors on Gumroad/Leanpub)
- **Frontend Masters**: JavaScript payment processing courses
- **Udemy**: "Complete Stripe Payments Developer Course"

### Newsletter & Updates
- **Stripe Developer Digest**: Subscribe at https://stripe.com/blog
- **Changelog**: https://stripe.com/blog/changelog

---

## Final Thoughts

You now have everything you need to build a production-ready SaaS payment system with Stripe. Remember:

1. **Start Simple**: One-time payments → Subscriptions → Advanced features
2. **Test Everything**: Use test mode extensively
3. **Webhooks Are Critical**: They're your source of truth
4. **Security First**: Never store card data, always verify webhooks
5. **Monitor Relentlessly**: Set up alerts and logs

**Your Next Steps:**
1. Create a Stripe test account
2. Build a simple checkout flow (follow the One-Time Payments section)
3. Add subscriptions
4. Set up webhooks
5. Test thoroughly
6. Go live!

**Remember**: Stripe handles the hard parts (PCI compliance, international payments, failed payment retries). Your job is to:
- Create great products
- Handle webhooks reliably
- Provide excellent customer support

Now go build that SaaS! 🚀

---

*Last Updated: November 29, 2025*
*Stripe API Version: 2024-12-18*
This tutorial covers everything from absolute basics to production-ready implementation. Each section builds on the previous one, with real code examples you can copy and adapt. The explanations are designed to help concepts "stick" by explaining not just how but why things work the way they do.