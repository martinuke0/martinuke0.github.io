---
title: "The Complete Guide to Building SaaS with Supabase: From Beginner to Hero"
date: 2025-11-28T17:17:00+02:00
draft: false
tags: ["supabase", "javascript", "saas", "postgresql", "authentication", "realtime", "storage"]
---

## Table of Contents
1. [What is Supabase?](#what-is-supabase)
2. [Setting Up Your First Supabase Project](#setting-up)
3. [Database Fundamentals](#database-fundamentals)
4. [Authentication (Auth)](#authentication)
5. [Row Level Security (RLS)](#row-level-security)
6. [Realtime Subscriptions](#realtime-subscriptions)
7. [Storage (File Uploads)](#storage)
8. [Edge Functions](#edge-functions)
9. [Building a Complete SaaS Application](#building-saas)
10. [Production Best Practices](#production-best-practices)
11. [Resources](#resources)

---

## What is Supabase?

Supabase is an open-source Firebase alternative built on PostgreSQL. Think of it as your **entire backend in a box**:

- **PostgreSQL Database**: A real, powerful SQL database (not a limited NoSQL solution)
- **Authentication**: Email, OAuth, magic links - all handled for you
- **Realtime**: Live data updates without writing WebSocket code
- **Storage**: File uploads with CDN delivery
- **Edge Functions**: Serverless backend logic
- **Auto-generated APIs**: REST and GraphQL APIs created automatically from your database

**Why Supabase for SaaS?**
- You focus on features, not infrastructure
- Built-in multi-tenancy with Row Level Security
- Scales from prototype to millions of users
- All the power of PostgreSQL (joins, triggers, functions)
- Open source = no vendor lock-in

---

## Setting Up Your First Supabase Project

### Step 1: Create Your Project

1. Go to [supabase.com](https://supabase.com) and sign up
2. Click "New Project"
3. Choose:
   - **Organization**: Your workspace name
   - **Project Name**: `my-saas-app`
   - **Database Password**: Generate a strong one (save it!)
   - **Region**: Choose closest to your users

**🚀 Pro Tip**: The database password is for direct database access. You rarely need it - the JavaScript client handles authentication automatically.

### Step 2: Install Supabase JavaScript Client

```bash
npm install @supabase/supabase-js
```

### Step 3: Get Your API Keys

In your Supabase dashboard:
1. Go to **Settings** → **API**
2. Copy:
   - **Project URL**: `https://yourproject.supabase.co`
   - **anon/public key**: Safe to use in frontend code

### Step 4: Initialize Supabase Client

Create a file `src/supabaseClient.js`:

```javascript
import { createClient } from '@supabase/supabase-js'

// These are SAFE to expose in frontend code
const supabaseUrl = 'https://yourproject.supabase.co'
const supabaseAnonKey = 'your-anon-key-here'

export const supabase = createClient(supabaseUrl, supabaseAnonKey)
```

**Why is the anon key safe?**
Because Supabase uses Row Level Security (RLS) policies on the database level. The key just identifies your project - actual security happens in PostgreSQL.

---

## Database Fundamentals

Supabase uses PostgreSQL, one of the most powerful databases in the world. Let's start simple and build up.

### Creating Your First Table

In Supabase Dashboard → **Table Editor** → **New Table**:

**Table Name**: `todos`

**Columns**:
- `id` (int8) - Primary Key, auto-increment ✓
- `user_id` (uuid) - Foreign key to `auth.users`
- `title` (text)
- `completed` (bool) - Default: false
- `created_at` (timestamptz) - Default: now()

**Or use SQL Editor**:

```sql
CREATE TABLE todos (
  id BIGSERIAL PRIMARY KEY,
  user_id UUID REFERENCES auth.users NOT NULL,
  title TEXT NOT NULL,
  completed BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now()
);
```

### Understanding the Schema

```
todos table
├── id: Unique identifier for each todo
├── user_id: Links todo to the user who created it
├── title: The actual todo text
├── completed: Whether it's done or not
└── created_at: When it was created
```

**Key Concepts**:
- **PRIMARY KEY**: Uniquely identifies each row
- **REFERENCES auth.users**: Creates a relationship - every todo belongs to a user
- **DEFAULT**: Auto-fills values when you don't provide them

### Basic Database Operations

#### 1. Insert (Create)

```javascript
import { supabase } from './supabaseClient'

// Add a new todo
const { data, error } = await supabase
  .from('todos')
  .insert([
    { 
      user_id: 'user-uuid-here',
      title: 'Learn Supabase',
      completed: false 
    }
  ])
  .select() // Returns the inserted row

if (error) console.error('Error:', error)
else console.log('Created:', data)
```

**What's happening?**
1. `.from('todos')` - Select the table
2. `.insert([...])` - Add new rows (always an array, even for one item)
3. `.select()` - Return the data you just inserted

#### 2. Select (Read)

```javascript
// Get all todos
const { data, error } = await supabase
  .from('todos')
  .select('*') // * means all columns

// Get specific columns
const { data } = await supabase
  .from('todos')
  .select('id, title, completed')

// Filter results
const { data } = await supabase
  .from('todos')
  .select('*')
  .eq('completed', false) // WHERE completed = false
  .order('created_at', { ascending: false }) // Newest first
```

**Common Filters**:
- `.eq('column', value)` - Equals
- `.neq('column', value)` - Not equals
- `.gt('column', value)` - Greater than
- `.lt('column', value)` - Less than
- `.like('column', '%pattern%')` - Text search
- `.in('column', [value1, value2])` - Match any in array

#### 3. Update

```javascript
const { data, error } = await supabase
  .from('todos')
  .update({ completed: true })
  .eq('id', 5) // Only update todo with id = 5
  .select()
```

**⚠️ Important**: Always add a filter (`.eq()`, `.match()`, etc.) or you'll update EVERY row!

#### 4. Delete

```javascript
const { error } = await supabase
  .from('todos')
  .delete()
  .eq('id', 5)
```

### Advanced Queries

#### Joins (Relationships)

Let's say you have a `profiles` table with user info:

```sql
CREATE TABLE profiles (
  id UUID REFERENCES auth.users PRIMARY KEY,
  username TEXT UNIQUE,
  avatar_url TEXT
);
```

Now join todos with their creator's profile:

```javascript
const { data } = await supabase
  .from('todos')
  .select(`
    *,
    profiles (
      username,
      avatar_url
    )
  `)
```

Result:
```javascript
[
  {
    id: 1,
    title: "Buy milk",
    completed: false,
    profiles: {
      username: "john_doe",
      avatar_url: "https://..."
    }
  }
]
```

**This is POWERFUL**: No need for multiple queries or manual joins. Supabase does it automatically.

#### Filtering on Related Tables

```javascript
// Get todos created by users with specific usernames
const { data } = await supabase
  .from('todos')
  .select('*, profiles!inner(username)')
  .eq('profiles.username', 'john_doe')
```

The `!inner` means "only return todos where profile exists" (INNER JOIN).

#### Count Queries

```javascript
const { count } = await supabase
  .from('todos')
  .select('*', { count: 'exact', head: true })
  .eq('completed', false)

console.log(`You have ${count} incomplete todos`)
```

#### Pagination

```javascript
const pageSize = 10
const page = 2

const { data } = await supabase
  .from('todos')
  .select('*')
  .range((page - 1) * pageSize, page * pageSize - 1)
  
// Page 1: range(0, 9) → rows 0-9
// Page 2: range(10, 19) → rows 10-19
```

### Full-Text Search

```javascript
// Search todos by title
const { data } = await supabase
  .from('todos')
  .select('*')
  .textSearch('title', 'supabase | postgres', {
    type: 'websearch',
    config: 'english'
  })
```

This uses PostgreSQL's powerful full-text search. The `|` means OR.

---

## Authentication

Authentication is one of Supabase's superpowers. It handles everything: sessions, tokens, password resets, OAuth providers.

### Email/Password Authentication

#### Sign Up

```javascript
const { data, error } = await supabase.auth.signUp({
  email: 'user@example.com',
  password: 'secure-password-123',
  options: {
    data: {
      // Additional user metadata
      first_name: 'John',
      age: 27
    }
  }
})

if (error) {
  console.error('Signup error:', error.message)
} else {
  console.log('User created:', data.user)
  console.log('Session:', data.session)
}
```

**What happens?**
1. User is created in `auth.users` table
2. Confirmation email is sent (if enabled)
3. Session is created with JWT tokens
4. User metadata is stored in `auth.users.raw_user_meta_data`

#### Sign In

```javascript
const { data, error } = await supabase.auth.signInWithPassword({
  email: 'user@example.com',
  password: 'secure-password-123'
})

if (error) {
  console.error('Login error:', error.message)
} else {
  console.log('Logged in:', data.user)
  // JWT tokens are automatically stored in localStorage
}
```

#### Get Current User

```javascript
const { data: { user } } = await supabase.auth.getUser()

if (user) {
  console.log('Logged in as:', user.email)
  console.log('User ID:', user.id)
  console.log('Metadata:', user.user_metadata)
} else {
  console.log('Not logged in')
}
```

#### Sign Out

```javascript
const { error } = await supabase.auth.signOut()
```

This clears the session and removes tokens from storage.

### OAuth Providers (Google, GitHub, etc.)

#### Setup

1. In Supabase Dashboard → **Authentication** → **Providers**
2. Enable provider (e.g., Google)
3. Add OAuth credentials from Google Console

#### Sign In with OAuth

```javascript
const { data, error } = await supabase.auth.signInWithOAuth({
  provider: 'google',
  options: {
    redirectTo: 'https://yourapp.com/auth/callback'
  }
})
```

**Flow**:
1. User clicks "Sign in with Google"
2. Redirected to Google
3. User authorizes
4. Redirected back to your app with session

#### Handling the Callback

```javascript
// On your callback page
const { data: { user } } = await supabase.auth.getUser()

if (user) {
  // User is logged in, redirect to dashboard
  window.location.href = '/dashboard'
}
```

### Magic Link (Passwordless)

```javascript
const { error } = await supabase.auth.signInWithOtp({
  email: 'user@example.com',
  options: {
    emailRedirectTo: 'https://yourapp.com/dashboard'
  }
})

if (!error) {
  alert('Check your email for the login link!')
}
```

User clicks link in email → automatically logged in.

### Phone Authentication

```javascript
// Send OTP
const { error } = await supabase.auth.signInWithOtp({
  phone: '+1234567890'
})

// Verify OTP
const { data, error } = await supabase.auth.verifyOtp({
  phone: '+1234567890',
  token: '123456',
  type: 'sms'
})
```

### Auth State Changes (Listening for Login/Logout)

```javascript
supabase.auth.onAuthStateChange((event, session) => {
  console.log('Auth event:', event) // SIGNED_IN, SIGNED_OUT, etc.
  
  if (event === 'SIGNED_IN') {
    console.log('User logged in:', session.user)
    // Redirect to dashboard, load user data, etc.
  }
  
  if (event === 'SIGNED_OUT') {
    console.log('User logged out')
    // Redirect to login page
  }
})
```

**Use cases**:
- React: Update UI when auth state changes
- Save data when user signs in
- Cleanup when user signs out

### Password Reset

```javascript
// Send reset email
const { error } = await supabase.auth.resetPasswordForEmail(
  'user@example.com',
  { redirectTo: 'https://yourapp.com/reset-password' }
)

// On reset page, update password
const { error } = await supabase.auth.updateUser({
  password: 'new-secure-password'
})
```

### Update User Metadata

```javascript
const { error } = await supabase.auth.updateUser({
  data: {
    first_name: 'Jane',
    theme: 'dark'
  }
})

// Access it later
const { data: { user } } = await supabase.auth.getUser()
console.log(user.user_metadata.theme) // 'dark'
```

### Email Confirmation

By default, users must confirm their email. To disable (for development):

Dashboard → **Authentication** → **Email** → Disable "Confirm email"

**For production, always require confirmation!**

---

## Row Level Security (RLS)

This is where Supabase becomes magical for multi-tenant SaaS. RLS policies run **in the database** - users can ONLY access data they're allowed to, even if they hack your frontend.

### The Problem Without RLS

```javascript
// User can read ANYONE'S todos! 😱
const { data } = await supabase.from('todos').select('*')
```

### The Solution: RLS Policies

Enable RLS on your table:

```sql
ALTER TABLE todos ENABLE ROW LEVEL SECURITY;
```

Now **nobody can access any data** until you create policies.

### Policy 1: Users Can Read Their Own Todos

```sql
CREATE POLICY "Users can read own todos"
ON todos
FOR SELECT
TO authenticated
USING (auth.uid() = user_id);
```

**Breaking it down**:
- `FOR SELECT` - This policy applies to reading data
- `TO authenticated` - Only logged-in users
- `USING (auth.uid() = user_id)` - WHERE clause: `current_user_id = row's user_id`

Now this works:

```javascript
// Automatically only returns current user's todos! 🎉
const { data } = await supabase.from('todos').select('*')
```

Supabase adds `WHERE auth.uid() = user_id` automatically.

### Policy 2: Users Can Insert Their Own Todos

```sql
CREATE POLICY "Users can insert own todos"
ON todos
FOR INSERT
TO authenticated
WITH CHECK (auth.uid() = user_id);
```

`WITH CHECK` validates the data **being inserted**. Users can't insert todos for other users.

```javascript
// ✅ Works - user_id matches logged-in user
await supabase.from('todos').insert([{
  user_id: currentUser.id,
  title: 'My todo'
}])

// ❌ Fails - user_id doesn't match
await supabase.from('todos').insert([{
  user_id: 'someone-elses-id',
  title: 'Hack attempt'
}])
```

### Policy 3: Users Can Update Their Own Todos

```sql
CREATE POLICY "Users can update own todos"
ON todos
FOR UPDATE
TO authenticated
USING (auth.uid() = user_id)
WITH CHECK (auth.uid() = user_id);
```

`USING` checks existing rows, `WITH CHECK` validates the update.

### Policy 4: Users Can Delete Their Own Todos

```sql
CREATE POLICY "Users can delete own todos"
ON todos
FOR DELETE
TO authenticated
USING (auth.uid() = user_id);
```

### All-in-One Policy

You can combine policies:

```sql
CREATE POLICY "Users manage own todos"
ON todos
FOR ALL
TO authenticated
USING (auth.uid() = user_id)
WITH CHECK (auth.uid() = user_id);
```

`FOR ALL` = SELECT, INSERT, UPDATE, DELETE.

### Advanced RLS: Team-Based Access

Let's say you have teams:

```sql
CREATE TABLE teams (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name TEXT NOT NULL
);

CREATE TABLE team_members (
  team_id UUID REFERENCES teams,
  user_id UUID REFERENCES auth.users,
  role TEXT, -- 'owner', 'admin', 'member'
  PRIMARY KEY (team_id, user_id)
);

CREATE TABLE projects (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  team_id UUID REFERENCES teams,
  name TEXT NOT NULL
);
```

Policy: Users can read projects from teams they belong to

```sql
CREATE POLICY "Team members can read team projects"
ON projects
FOR SELECT
TO authenticated
USING (
  EXISTS (
    SELECT 1 FROM team_members
    WHERE team_members.team_id = projects.team_id
    AND team_members.user_id = auth.uid()
  )
);
```

**How it works**:
1. User queries projects
2. For each project, PostgreSQL checks: "Is this user in the team_members table for this project's team?"
3. Only matching projects are returned

### Public Access

```sql
-- Anyone can read, even anonymous users
CREATE POLICY "Public read access"
ON blog_posts
FOR SELECT
TO anon, authenticated
USING (published = true);
```

### Testing RLS Policies

```sql
-- Test as specific user
SET request.jwt.claims.sub = 'user-uuid-here';

-- Query as that user
SELECT * FROM todos;

-- Reset
RESET ALL;
```

### RLS Best Practices for SaaS

1. **Always enable RLS** on tables with user data
2. **Start restrictive**, then loosen as needed
3. **Use helper functions** for complex logic:

```sql
CREATE FUNCTION is_team_admin(team_id UUID)
RETURNS BOOLEAN AS $$
  SELECT EXISTS (
    SELECT 1 FROM team_members
    WHERE team_members.team_id = $1
    AND team_members.user_id = auth.uid()
    AND team_members.role = 'admin'
  );
$$ LANGUAGE SQL SECURITY DEFINER;

-- Use in policy
CREATE POLICY "Only admins can delete projects"
ON projects
FOR DELETE
TO authenticated
USING (is_team_admin(team_id));
```

---

## Realtime Subscriptions

Supabase can push database changes to your frontend in real-time. Perfect for chat apps, collaborative tools, live dashboards.

### How Realtime Works

1. Your database changes (INSERT, UPDATE, DELETE)
2. PostgreSQL fires a notification
3. Supabase broadcasts it to subscribed clients
4. Your frontend updates instantly

### Basic Subscription

```javascript
// Subscribe to all changes on todos table
const channel = supabase
  .channel('todos-changes')
  .on(
    'postgres_changes',
    {
      event: '*', // INSERT, UPDATE, DELETE, or * for all
      schema: 'public',
      table: 'todos'
    },
    (payload) => {
      console.log('Change detected:', payload)
      // payload.eventType: 'INSERT', 'UPDATE', or 'DELETE'
      // payload.new: The new row data
      // payload.old: The old row data (for UPDATE/DELETE)
    }
  )
  .subscribe()
```

### React Example: Live Todo List

```javascript
import { useEffect, useState } from 'react'
import { supabase } from './supabaseClient'

function TodoList() {
  const [todos, setTodos] = useState([])

  useEffect(() => {
    // Initial fetch
    fetchTodos()

    // Subscribe to changes
    const channel = supabase
      .channel('todos-realtime')
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'todos' },
        (payload) => {
          if (payload.eventType === 'INSERT') {
            setTodos(prev => [...prev, payload.new])
          } else if (payload.eventType === 'UPDATE') {
            setTodos(prev =>
              prev.map(todo =>
                todo.id === payload.new.id ? payload.new : todo
              )
            )
          } else if (payload.eventType === 'DELETE') {
            setTodos(prev =>
              prev.filter(todo => todo.id !== payload.old.id)
            )
          }
        }
      )
      .subscribe()

    // Cleanup
    return () => {
      supabase.removeChannel(channel)
    }
  }, [])

  async function fetchTodos() {
    const { data } = await supabase.from('todos').select('*')
    setTodos(data || [])
  }

  return (
    <ul>
      {todos.map(todo => (
        <li key={todo.id}>{todo.title}</li>
      ))}
    </ul>
  )
}
```

**What happens**: User A adds a todo → User B's list updates instantly, no refresh needed.

### Filtering Realtime Events

```javascript
// Only listen to completed todos
supabase
  .channel('completed-todos')
  .on(
    'postgres_changes',
    {
      event: 'UPDATE',
      schema: 'public',
      table: 'todos',
      filter: 'completed=eq.true' // Only when completed becomes true
    },
    (payload) => {
      console.log('Todo completed:', payload.new)
    }
  )
  .subscribe()
```

### Presence (Who's Online)

Track which users are currently viewing a page:

```javascript
const channel = supabase.channel('room1')

// Join the room
channel
  .on('presence', { event: 'sync' }, () => {
    const state = channel.presenceState()
    console.log('Online users:', state)
  })
  .subscribe(async (status) => {
    if (status === 'SUBSCRIBED') {
      await channel.track({
        user: 'john_doe',
        online_at: new Date().toISOString()
      })
    }
  })

// Leave when user closes tab
window.addEventListener('beforeunload', () => {
  channel.untrack()
})
```

### Broadcast (Send Custom Messages)

```javascript
const channel = supabase.channel('game-room')

// Send a message
channel
  .subscribe(async (status) => {
    if (status === 'SUBSCRIBED') {
      channel.send({
        type: 'broadcast',
        event: 'player-move',
        payload: { x: 10, y: 20 }
      })
    }
  })

// Receive messages
channel
  .on('broadcast', { event: 'player-move' }, (payload) => {
    console.log('Player moved to:', payload.payload)
  })
  .subscribe()
```

### Realtime Best Practices

1. **Unsubscribe when done**: Prevents memory leaks
2. **Use filters**: Don't broadcast everything
3. **Handle reconnections**: Realtime auto-reconnects, but refetch data on reconnect
4. **Combine with RLS**: Users only get updates for data they can access

---

## Storage (File Uploads)

Supabase Storage handles file uploads with CDN delivery, access control, and image transformations.

### Creating a Bucket

Dashboard → **Storage** → **New Bucket**:

- **Name**: `avatars`
- **Public**: Yes (files accessible without auth)

Or via code:

```javascript
const { data, error } = await supabase.storage.createBucket('avatars', {
  public: true
})
```

### Uploading Files

```javascript
const file = event.target.files[0] // From <input type="file">

const { data, error } = await supabase.storage
  .from('avatars')
  .upload(`public/${user.id}/avatar.png`, file, {
    cacheControl: '3600',
    upsert: true // Overwrite if exists
  })

if (error) {
  console.error('Upload error:', error.message)
} else {
  console.log('Uploaded:', data.path)
  // data.path = 'public/user-id/avatar.png'
}
```

### Getting Public URL

```javascript
const { data } = supabase.storage
  .from('avatars')
  .getPublicUrl('public/user-id/avatar.png')

console.log('Image URL:', data.publicUrl)
// https://yourproject.supabase.co/storage/v1/object/public/avatars/public/user-id/avatar.png
```

### Downloading Files

```javascript
const { data, error } = await supabase.storage
  .from('avatars')
  .download('public/user-id/avatar.png')

// data is a Blob
const url = URL.createObjectURL(data)
document.getElementById('avatar').src = url
```

### Listing Files

```javascript
const { data, error } = await supabase.storage
  .from('avatars')
  .list('public/user-id', {
    limit: 100,
    offset: 0,
    sortBy: { column: 'name', order: 'asc' }
  })

data.forEach(file => {
  console.log(file.name, file.created_at, file.metadata.size)
})
```

### Deleting Files

```javascript
const { error } = await supabase.storage
  .from('avatars')
  .remove(['public/user-id/avatar.png'])
```

### Image Transformations

Resize, crop, and optimize images on-the-fly:

```javascript
const { data } = supabase.storage
  .from('avatars')
  .getPublicUrl('public/user-id/avatar.png', {
    transform: {
      width: 200,
      height: 200,
      resize: 'cover', // 'cover', 'contain', 'fill'
      quality: 80
    }
  })

// URL now returns a 200x200px, optimized image
```

### Private Buckets & Access Control

Create a private bucket:

```javascript
const { data, error } = await supabase.storage.createBucket('documents', {
  public: false // Private bucket
})
```

Set RLS policies on storage:

```sql
-- Users can upload to their own folder
CREATE POLICY "Users can upload own files"
ON storage.objects
FOR INSERT
TO authenticated
WITH CHECK (
  bucket_id = 'documents' AND
  (storage.foldername(name))[1] = auth.uid()::text
);

-- Users can read their own files
CREATE POLICY "Users can read own files"
ON storage.objects
FOR SELECT
TO authenticated
USING (
  bucket_id = 'documents' AND
  (storage.foldername(name))[1] = auth.uid()::text
);
```

Now users can only access files in their folder:

```javascript
// ✅ Works - uploading to own folder
await supabase.storage
  .from('documents')
  .upload(`${user.id}/report.pdf`, file)

// ❌ Fails - trying to access someone else's folder
await supabase.storage
  .from('documents')
  .download('other-user-id/report.pdf')
```

### Get Signed URLs (Temporary Access)

```javascript
const { data, error } = await supabase.storage
  .from('documents')
  .createSignedUrl('private/report.pdf', 3600) // Valid for 1 hour

console.log('Temp URL:', data.signedUrl)
// Share this URL - expires in 1 hour
```

### Full Upload Example with Progress

```javascript
async function uploadWithProgress(file) {
  const filePath = `${user.id}/${Date.now()}-${file.name}`

  const { data, error } = await supabase.storage
    .from('uploads')
    .upload(filePath, file, {
      cacheControl: '3600',
      upsert: false,
      onUploadProgress: (progress) => {
        const percent = (progress.loaded / progress.total) * 100
        console.log(`Upload: ${percent.toFixed(0)}%`)
        // Update progress bar here
      }
    })

  if (error) throw error

  // Get public URL
  const { data: urlData } = supabase.storage
    .from('uploads')
    .getPublicUrl(filePath)

  return urlData.publicUrl
}
```

---

## Edge Functions

Edge Functions are serverless TypeScript/JavaScript functions that run on Supabase's global network. Use them for:

- Webhooks (Stripe, SendGrid)
- Scheduled tasks (cron jobs)
- Server-side logic (sending emails, calling external APIs)
- Custom endpoints

### Creating Your First Edge Function

Install Supabase CLI:

```bash
npm install -g supabase
```

Initialize:

```bash
supabase init
supabase functions new hello-world
```

This creates `supabase/functions/hello-world/index.ts`:

```typescript
import { serve } from "https://deno.land/std@0.168.0/http/server.ts"

serve(async (req) => {
  const { name } = await req.json()

  return new Response(
    JSON.stringify({ message: `Hello, ${name}!` }),
    { headers: { "Content-Type": "application/json" } }
  )
})
```

### Deploying

```bash
supabase functions deploy hello-world
```

### Invoking from Frontend

```javascript
const { data, error } = await supabase.functions.invoke('hello-world', {
  body: { name: 'John' }
})

console.log(data) // { message: 'Hello, John!' }
```

### Accessing Supabase from Edge Functions

```typescript
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'
import { serve } from 'https://deno.land/std@0.168.0/http/server.ts'

serve(async (req) => {
  const supabase = createClient(
    Deno.env.get('SUPABASE_URL') ?? '',
    Deno.env.get('SUPABASE_ANON_KEY') ?? ''
  )

  const { data } = await supabase.from('todos').select('*')

  return new Response(JSON.stringify(data), {
    headers: { 'Content-Type': 'application/json' }
  })
})
```

### Stripe Webhook Example

```typescript
import { serve } from 'https://deno.land/std@0.168.0/http/server.ts'
import Stripe from 'https://esm.sh/stripe@14.0.0'

const stripe = new Stripe(Deno.env.get('STRIPE_SECRET_KEY') ?? '', {
  apiVersion: '2023-10-16'
})

serve(async (req) => {
  const signature = req.headers.get('stripe-signature')
  const body = await req.text()

  try {
    const event = stripe.webhooks.constructEvent(
      body,
      signature!,
      Deno.env.get('STRIPE_WEBHOOK_SECRET') ?? ''
    )

    if (event.type === 'checkout.session.completed') {
      const session = event.data.object
      // Update user subscription in database
      console.log('Payment successful:', session.id)
    }

    return new Response(JSON.stringify({ received: true }), {
      status: 200
    })
  } catch (err) {
    return new Response(JSON.stringify({ error: err.message }), {
      status: 400
    })
  }
})
```

### Scheduled Functions (Cron Jobs)

Add to `supabase/functions/cleanup/index.ts`:

```typescript
import { serve } from 'https://deno.land/std@0.168.0/http/server.ts'
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

serve(async (req) => {
  const supabase = createClient(
    Deno.env.get('SUPABASE_URL') ?? '',
    Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? ''
  )

  // Delete todos older than 30 days
  const { error } = await supabase
    .from('todos')
    .delete()
    .lt('created_at', new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString())

  if (error) throw error

  return new Response(JSON.stringify({ success: true }), {
    headers: { 'Content-Type': 'application/json' }
  })
})
```

Schedule it via Dashboard → **Edge Functions** → Select function → **Settings** → Add cron schedule:

```
0 2 * * * # Run daily at 2 AM
```

---

## Building a Complete SaaS Application {#building-saas}

Let's build a complete **Task Management SaaS** with teams, projects, and real-time collaboration.

### Database Schema

```sql
-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Profiles table
CREATE TABLE profiles (
  id UUID REFERENCES auth.users PRIMARY KEY,
  username TEXT UNIQUE NOT NULL,
  full_name TEXT,
  avatar_url TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Teams table
CREATE TABLE teams (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name TEXT NOT NULL,
  created_by UUID REFERENCES auth.users NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Team members
CREATE TABLE team_members (
  team_id UUID REFERENCES teams ON DELETE CASCADE,
  user_id UUID REFERENCES auth.users ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'member')),
  joined_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (team_id, user_id)
);

-- Projects
CREATE TABLE projects (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  team_id UUID REFERENCES teams ON DELETE CASCADE NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  created_by UUID REFERENCES auth.users NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Tasks
CREATE TABLE tasks (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id UUID REFERENCES projects ON DELETE CASCADE NOT NULL,
  title TEXT NOT NULL,
  description TEXT,
  status TEXT NOT NULL DEFAULT 'todo' CHECK (status IN ('todo', 'in_progress', 'done')),
  assigned_to UUID REFERENCES auth.users,
  created_by UUID REFERENCES auth.users NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- Enable RLS
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE teams ENABLE ROW LEVEL SECURITY;
ALTER TABLE team_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;
```

### RLS Policies

```sql
-- Profiles: Users can read all profiles, update own
CREATE POLICY "Public profiles are viewable" ON profiles
  FOR SELECT USING (true);

CREATE POLICY "Users can update own profile" ON profiles
  FOR UPDATE USING (auth.uid() = id);

-- Teams: Team members can read their teams
CREATE POLICY "Team members can view teams" ON teams
  FOR SELECT USING (
    EXISTS (
      SELECT 1 FROM team_members
      WHERE team_members.team_id = teams.id
      AND team_members.user_id = auth.uid()
    )
  );

CREATE POLICY "Anyone can create teams" ON teams
  FOR INSERT WITH CHECK (auth.uid() = created_by);

-- Team members: Can view and manage based on role
CREATE POLICY "Team members can view team members" ON team_members
  FOR SELECT USING (
    EXISTS (
      SELECT 1 FROM team_members tm
      WHERE tm.team_id = team_members.team_id
      AND tm.user_id = auth.uid()
    )
  );

-- Projects: Team members can view projects
CREATE POLICY "Team members can view projects" ON projects
  FOR SELECT USING (
    EXISTS (
      SELECT 1 FROM team_members
      WHERE team_members.team_id = projects.team_id
      AND team_members.user_id = auth.uid()
    )
  );

CREATE POLICY "Team members can create projects" ON projects
  FOR INSERT WITH CHECK (
    EXISTS (
      SELECT 1 FROM team_members
      WHERE team_members.team_id = projects.team_id
      AND team_members.user_id = auth.uid()
    )
  );

-- Tasks: Team members can manage tasks
CREATE POLICY "Team members can view tasks" ON tasks
  FOR SELECT USING (
    EXISTS (
      SELECT 1 FROM projects p
      JOIN team_members tm ON tm.team_id = p.team_id
      WHERE p.id = tasks.project_id
      AND tm.user_id = auth.uid()
    )
  );

CREATE POLICY "Team members can create tasks" ON tasks
  FOR INSERT WITH CHECK (
    EXISTS (
      SELECT 1 FROM projects p
      JOIN team_members tm ON tm.team_id = p.team_id
      WHERE p.id = tasks.project_id
      AND tm.user_id = auth.uid()
    )
  );

CREATE POLICY "Team members can update tasks" ON tasks
  FOR UPDATE USING (
    EXISTS (
      SELECT 1 FROM projects p
      JOIN team_members tm ON tm.team_id = p.team_id
      WHERE p.id = tasks.project_id
      AND tm.user_id = auth.uid()
    )
  );
```

### Database Functions

```sql
-- Function to auto-create profile on signup
CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO profiles (id, username, full_name, avatar_url)
  VALUES (
    NEW.id,
    NEW.raw_user_meta_data->>'username',
    NEW.raw_user_meta_data->>'full_name',
    NEW.raw_user_meta_data->>'avatar_url'
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Trigger on auth.users
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION handle_new_user();

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger on tasks
CREATE TRIGGER tasks_updated_at
  BEFORE UPDATE ON tasks
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();
```

### React Application Example

```javascript
import { useEffect, useState } from 'react'
import { supabase } from './supabaseClient'

function App() {
  const [user, setUser] = useState(null)
  const [tasks, setTasks] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // Get initial session
    supabase.auth.getSession().then(({ data: { session } }) => {
      setUser(session?.user ?? null)
      if (session?.user) {
        fetchTasks()
      }
      setLoading(false)
    })

    // Listen for auth changes
    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      (_event, session) => {
        setUser(session?.user ?? null)
        if (session?.user) {
          fetchTasks()
        } else {
          setTasks([])
        }
      }
    )

    return () => subscription.unsubscribe()
  }, [])

  useEffect(() => {
    if (!user) return

    // Subscribe to task changes
    const channel = supabase
      .channel('tasks-changes')
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'tasks' },
        (payload) => {
          if (payload.eventType === 'INSERT') {
            setTasks(prev => [...prev, payload.new])
          } else if (payload.eventType === 'UPDATE') {
            setTasks(prev =>
              prev.map(task =>
                task.id === payload.new.id ? payload.new : task
              )
            )
          } else if (payload.eventType === 'DELETE') {
            setTasks(prev => prev.filter(task => task.id !== payload.old.id))
          }
        }
      )
      .subscribe()

    return () => {
      supabase.removeChannel(channel)
    }
  }, [user])

  async function fetchTasks() {
    const { data, error } = await supabase
      .from('tasks')
      .select(`
        *,
        project:projects(name),
        assigned:profiles!assigned_to(username, avatar_url)
      `)
      .order('created_at', { ascending: false })

    if (error) {
      console.error('Error fetching tasks:', error)
    } else {
      setTasks(data || [])
    }
  }

  async function signIn() {
    await supabase.auth.signInWithOAuth({ provider: 'google' })
  }

  async function signOut() {
    await supabase.auth.signOut()
  }

  async function createTask(title) {
    const { error } = await supabase
      .from('tasks')
      .insert([{
        project_id: 'your-project-id',
        title,
        created_by: user.id
      }])

    if (error) console.error('Error creating task:', error)
  }

  async function updateTaskStatus(taskId, status) {
    const { error } = await supabase
      .from('tasks')
      .update({ status })
      .eq('id', taskId)

    if (error) console.error('Error updating task:', error)
  }

  if (loading) return <div>Loading...</div>

  if (!user) {
    return (
      <div>
        <h1>Task Manager</h1>
        <button onClick={signIn}>Sign In with Google</button>
      </div>
    )
  }

  return (
    <div>
      <header>
        <h1>Task Manager</h1>
        <p>Welcome, {user.email}</p>
        <button onClick={signOut}>Sign Out</button>
      </header>

      <main>
        <section>
          <h2>Tasks ({tasks.length})</h2>
          <button onClick={() => {
            const title = prompt('Task title:')
            if (title) createTask(title)
          }}>
            Add Task
          </button>

          <div>
            {tasks.map(task => (
              <div key={task.id} style={{
                padding: '10px',
                margin: '10px 0',
                border: '1px solid #ddd',
                borderRadius: '5px'
              }}>
                <h3>{task.title}</h3>
                {task.description && <p>{task.description}</p>}
                <div>
                  <span>Status: </span>
                  <select
                    value={task.status}
                    onChange={(e) => updateTaskStatus(task.id, e.target.value)}
                  >
                    <option value="todo">To Do</option>
                    <option value="in_progress">In Progress</option>
                    <option value="done">Done</option>
                  </select>
                </div>
                <small>
                  Project: {task.project?.name} |
                  Assigned to: {task.assigned?.username || 'Unassigned'}
                </small>
              </div>
            ))}
          </div>
        </section>
      </main>
    </div>
  )
}

export default App
```

---

## Production Best Practices {#production-best-practices}

### 1. Environment Variables

Never hardcode keys in your code:

```javascript
// .env.local
VITE_SUPABASE_URL=your-project-url
VITE_SUPABASE_ANON_KEY=your-anon-key

// React (Vite)
const supabaseUrl = import.meta.env.VITE_SUPABASE_URL
const supabaseKey = import.meta.env.VITE_SUPABASE_ANON_KEY

// Next.js
const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL
const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
```

### 2. Connection Pooling

For serverless functions, use connection pooling:

Dashboard → **Settings** → **Database** → Enable **Connection Pooling**

Use the pooler connection string in your backend:

```javascript
const { Pool } = require('pg')

const pool = new Pool({
  connectionString: process.env.DATABASE_POOLER_URL
})
```

### 3. Database Indexing

Add indexes for frequently queried columns:

```sql
-- Index on foreign keys
CREATE INDEX idx_tasks_project_id ON tasks(project_id);
CREATE INDEX idx_tasks_assigned_to ON tasks(assigned_to);
CREATE INDEX idx_team_members_user_id ON team_members(user_id);

-- Index for filtering
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_created_at ON tasks(created_at DESC);

-- Composite index
CREATE INDEX idx_tasks_project_status ON tasks(project_id, status);
```

### 4. Database Backups

Dashboard → **Settings** → **Database** → **Backups**

- Free tier: Daily backups (7 days retention)
- Pro: Point-in-time recovery

### 5. Security Checklist

- ✅ Enable RLS on all tables with user data
- ✅ Test policies thoroughly
- ✅ Use service role key only in secure backend
- ✅ Enable email confirmation for production
- ✅ Set up MFA for admin accounts
- ✅ Configure CAPTCHA for auth forms
- ✅ Review audit logs regularly

### 6. Performance Optimization

**Use select() to limit columns:**

```javascript
// ❌ Fetches all columns
await supabase.from('tasks').select('*')

// ✅ Only what you need
await supabase.from('tasks').select('id, title, status')
```

**Paginate large results:**

```javascript
const pageSize = 20
const { data } = await supabase
  .from('tasks')
  .select('*')
  .range(0, pageSize - 1)
```

**Use explain to analyze queries:**

```sql
EXPLAIN ANALYZE
SELECT * FROM tasks WHERE project_id = 'some-id';
```

### 7. Error Handling

Always handle errors gracefully:

```javascript
async function createTask(task) {
  try {
    const { data, error } = await supabase
      .from('tasks')
      .insert([task])
      .select()

    if (error) {
      console.error('Supabase error:', error)
      throw new Error('Failed to create task')
    }

    return data[0]
  } catch (err) {
    console.error('Unexpected error:', err)
    throw err
  }
}
```

### 8. Monitoring

Dashboard → **Logs** → View:
- Database logs
- Auth logs
- Realtime logs
- Storage logs
- Edge Function logs

Set up alerts for:
- High error rates
- Slow queries
- Failed auth attempts
- Storage quota

### 9. Cost Optimization

**Free tier limits:**
- 500 MB database
- 1 GB file storage
- 2 GB bandwidth
- 50,000 monthly active users

**To optimize:**
- Use image transformations (resize on-the-fly)
- Enable RLS to reduce over-fetching
- Use CDN for static assets
- Archive old data
- Monitor usage in Dashboard → **Settings** → **Billing**

### 10. Migrations

Track schema changes with migrations:

```bash
# Create migration
supabase migration new add_comments_table

# Edit supabase/migrations/timestamp_add_comments_table.sql
CREATE TABLE comments (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  task_id UUID REFERENCES tasks,
  user_id UUID REFERENCES auth.users,
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

# Apply migration
supabase db push
```

### 11. Testing

Use local Supabase for testing:

```bash
# Start local instance
supabase start

# Run tests against local database
npm test
```

### 12. CI/CD Integration

```yaml
# .github/workflows/test.yml
name: Test
on: [push]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: supabase/setup-cli@v1
      - run: supabase start
      - run: npm install
      - run: npm test
```

---

## Resources {#resources}

### Official Documentation

- **Supabase Docs**: [supabase.com/docs](https://supabase.com/docs)
- **JavaScript Client**: [supabase.com/docs/reference/javascript](https://supabase.com/docs/reference/javascript)
- **Database Reference**: [supabase.com/docs/guides/database](https://supabase.com/docs/guides/database)
- **CLI Reference**: [supabase.com/docs/reference/cli](https://supabase.com/docs/reference/cli)

### Learning Resources

- **Supabase YouTube**: [youtube.com/@supabase](https://youtube.com/@supabase)
- **Examples Repository**: [github.com/supabase/supabase/tree/master/examples](https://github.com/supabase/supabase/tree/master/examples)
- **Supabase Blog**: [supabase.com/blog](https://supabase.com/blog)

### Community

- **Discord**: [discord.supabase.com](https://discord.supabase.com)
- **GitHub Discussions**: [github.com/supabase/supabase/discussions](https://github.com/supabase/supabase/discussions)
- **Twitter**: [@supabase](https://twitter.com/supabase)

### Tools

- **Supabase CLI**: Command-line tool for local development
- **Studio**: Built-in database GUI
- **dbdev**: PostgreSQL package manager
- **pg_graphql**: GraphQL extension for PostgreSQL

### Integrations

- **Next.js**: [supabase.com/docs/guides/getting-started/quickstarts/nextjs](https://supabase.com/docs/guides/getting-started/quickstarts/nextjs)
- **React**: [supabase.com/docs/guides/getting-started/quickstarts/reactjs](https://supabase.com/docs/guides/getting-started/quickstarts/reactjs)
- **Vue**: [supabase.com/docs/guides/getting-started/quickstarts/vue](https://supabase.com/docs/guides/getting-started/quickstarts/vue)
- **Flutter**: [supabase.com/docs/guides/getting-started/quickstarts/flutter](https://supabase.com/docs/guides/getting-started/quickstarts/flutter)
- **Svelte**: [supabase.com/docs/guides/getting-started/quickstarts/sveltekit](https://supabase.com/docs/guides/getting-started/quickstarts/sveltekit)

### Starter Templates

- **SaaS Starter**: [github.com/supabase-community/supabase-saas-starter](https://github.com/supabase-community/supabase-saas-starter)
- **Next.js Auth**: [github.com/supabase/auth-helpers/tree/main/examples/nextjs](https://github.com/supabase/auth-helpers/tree/main/examples/nextjs)
- **React Native**: [github.com/supabase-community/react-native-starter](https://github.com/supabase-community/react-native-starter)

### Advanced Topics

- **PostgREST**: [postgrest.org](https://postgrest.org) - The REST API behind Supabase
- **PostgreSQL Docs**: [postgresql.org/docs](https://www.postgresql.org/docs/)
- **Row Level Security**: [postgresql.org/docs/current/ddl-rowsecurity.html](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)

---

** Conclusion - Your next steps:**
1. Create a Supabase project
2. Design your database schema
3. Set up authentication
4. Enable RLS policies
5. Build your frontend
6. Deploy and monitor

Supabase handles the infrastructure so you can focus on building features your users love. Now go build that SaaS! 
