---
title: "The Complete Guide to KafkaJS: From Beginner to Hero"
date: 2025-12-03T20:17:00+02:00
draft: false
tags: ["kafka", "kafkajs", "messaging", "event-streaming", "microservices", "nodejs"]
---

## Table of Contents
1. [Introduction: Why Kafka and KafkaJS Matter](#introduction)
2. [Understanding Kafka Fundamentals](#kafka-fundamentals)
3. [Setting Up Your Development Environment](#setup)
4. [Your First KafkaJS Producer](#first-producer)
5. [Your First KafkaJS Consumer](#first-consumer)
6. [Advanced Producer Patterns](#advanced-producer)
7. [Advanced Consumer Patterns](#advanced-consumer)
8. [Schema Management and Serialization](#schema-management)
9. [Error Handling and Resilience](#error-handling)
10. [Performance Optimization](#performance)
11. [Production Deployment](#production)
12. [Resources and Further Learning](#resources)

---

## Introduction: Why Kafka and KafkaJS Matter {#introduction}

Apache Kafka has become the backbone of modern data architecture. Think of it as the **central nervous system** for your applications:

- **Event Streaming**: Real-time data flow between services
- **Microservices Communication**: Decoupled, scalable architecture
- **Data Pipeline**: Reliable data processing at scale
- **Event Sourcing**: Immutable log of all events
- **Stream Processing**: Real-time analytics and transformations

**Why KafkaJS?**
KafkaJS is the modern, promise-based Node.js client for Apache Kafka. While Java has the official client, KafkaJS brings Kafka's power to the JavaScript ecosystem with:

✅ **Modern API**: Promise-based, async/await friendly  
✅ **TypeScript Support**: Full type safety  
✅ **Lightweight**: No JVM dependency  
✅ **Production Ready**: Battle-tested in enterprise environments  
✅ **Active Development**: Regular updates and community support  

**The Mental Model**: Think of Kafka as a distributed log system. Producers write messages to topics, consumers read from those topics. It's like a newspaper where:
- **Topics** = Newspaper sections (Sports, Business, Technology)
- **Messages** = Individual articles
- **Partitions** = Multiple pages per section (parallel processing)
- **Consumers** = Readers subscribing to specific sections

---

## Understanding Kafka Fundamentals {#kafka-fundamentals}

Before writing code, let's understand the core concepts that make Kafka powerful.

### 1. **Topics and Partitions**

A **topic** is a category or feed name to which messages are published. Topics are split into **partitions** for scalability:

```
Topic: "user-events"
├── Partition 0 (messages 0, 3, 6...)
├── Partition 1 (messages 1, 4, 7...)
└── Partition 2 (messages 2, 5, 8...)
```

**Why partitions?**
- **Parallelism**: Multiple consumers can read from different partitions simultaneously
- **Scalability**: Distribute load across multiple servers
- **Ordering**: Messages within a partition maintain strict order

### 2. **Producers and Consumers**

**Producers** write messages to topics:
```javascript
// Producer sends message
await producer.send({
  topic: 'user-events',
  messages: [{ key: 'user-123', value: '{"action": "login"}' }]
})
```

**Consumers** read messages from topics:
```javascript
// Consumer receives message
await consumer.run({
  eachMessage: async ({ message }) => {
    console.log('Received:', message.value.toString())
  }
})
```

### 3. **Consumer Groups**

Multiple consumers can form a **consumer group** to process messages in parallel:

```
Topic: "user-events" (3 partitions)
├── Consumer Group A
│   ├── Consumer 1 → Partition 0
│   ├── Consumer 2 → Partition 1
│   └── Consumer 3 → Partition 2
└── Consumer Group B
    └── Consumer 1 → All partitions (if group size < partitions)
```

**Key Rules:**
- Each partition is consumed by at most one consumer in a group
- Consumer groups enable load balancing and fault tolerance
- If a consumer fails, partitions are rebalanced

### 4. **Offsets and Committing**

Each message in a partition has a unique **offset** (sequential number):

```
Partition 0:
[0] [1] [2] [3] [4] [5] [6] [7] [8] [9]
 ^           ^           ^
 |           |           |
last        current     next
committed   offset     message
```

**Committing offsets** tells Kafka which messages you've processed. This enables:
- **At-least-once delivery**: Replay messages if consumer crashes
- **Exactly-once semantics**: With proper handling and idempotent processing

### 5. **Message Structure**

Kafka messages consist of:

```javascript
{
  key: 'user-123',        // Optional: Determines partition
  value: '{"action": "login"}', // Required: Actual data
  headers: {              // Optional: Metadata
    'source': 'web-app',
    'timestamp': '1634567890'
  },
  timestamp: 1634567890123, // Optional: Event time
  partition: 0,            // Assigned by Kafka
  offset: 42               // Position in partition
}
```

**Key Insights:**
- **Key**: Controls which partition (same key = same partition)
- **Value**: Your actual data (JSON, Avro, protobuf, etc.)
- **Headers**: Metadata for routing, tracing, etc.

---

## Setting Up Your Development Environment {#setup}

### Option 1: Docker (Recommended)

Create a `docker-compose.yml` file:

```yaml
version: '3'
services:
  zookeeper:
    image: confluentinc/cp-zookeeper:7.3.0
    environment:
      ZOOKEEPER_CLIENT_PORT: 2181
      ZOOKEEPER_TICK_TIME: 2000
    ports:
      - "2181:2181"

  kafka:
    image: confluentinc/cp-kafka:7.3.0
    depends_on:
      - zookeeper
    ports:
      - "9092:9092"
      - "9101:9101"
    environment:
      KAFKA_BROKER_ID: 1
      KAFKA_ZOOKEEPER_CONNECT: 'zookeeper:2181'
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: PLAINTEXT:PLAINTEXT,PLAINTEXT_HOST:PLAINTEXT
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:29092,PLAINTEXT_HOST://localhost:9092
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
      KAFKA_TRANSACTION_STATE_LOG_MIN_ISR: 1
      KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR: 1
      KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS: 0
      KAFKA_JMX_PORT: 9101
      KAFKA_JMX_HOSTNAME: localhost
      KAFKA_AUTO_CREATE_TOPICS_ENABLE: 'true'

  kafka-ui:
    image: provectuslabs/kafka-ui:latest
    depends_on:
      - kafka
    ports:
      - "8080:8080"
    environment:
      KAFKA_CLUSTERS_0_NAME: local
      KAFKA_CLUSTERS_0_BOOTSTRAPSERVERS: kafka:29092
      KAFKA_CLUSTERS_0_ZOOKEEPER: zookeeper:2181
```

Start your Kafka cluster:

```bash
docker-compose up -d
```

Access Kafka UI at `http://localhost:8080` to visualize topics and messages.

### Option 2: Local Installation

For development without Docker:

```bash
# Download Kafka
wget https://downloads.apache.org/kafka/3.5.0/kafka_2.13-3.5.0.tgz
tar -xzf kafka_2.13-3.5.0.tgz
cd kafka_2.13-3.5.0

# Start Zookeeper
bin/zookeeper-server-start.sh config/zookeeper.properties

# Start Kafka (in new terminal)
bin/kafka-server-start.sh config/server.properties
```

### Installing KafkaJS

```bash
npm install kafkajs
# or
yarn add kafkajs

# For TypeScript
npm install --save-dev @types/node
```

### Basic Configuration

Create `kafkaConfig.js`:

```javascript
const { Kafka } = require('kafkajs')

// Development configuration
const kafka = new Kafka({
  clientId: 'my-app',
  brokers: ['localhost:9092'],
  // For production, add more brokers for redundancy
  // brokers: ['kafka1:9092', 'kafka2:9092', 'kafka3:9092'],
  
  // SSL configuration for production
  // ssl: {
  //   rejectUnauthorized: false,
  //   ca: [fs.readFileSync('./ca.pem', 'utf-8')],
  //   key: fs.readFileSync('./service.key', 'utf-8'),
  //   cert: fs.readFileSync('./service.cert', 'utf-8'),
  // },
  
  // SASL authentication
  // sasl: {
  //   mechanism: 'plain',
  //   username: process.env.KAFKA_USERNAME,
  //   password: process.env.KAFKA_PASSWORD,
  // },
})

module.exports = { kafka }
```

---

## Your First KafkaJS Producer {#first-producer}

Let's build a simple producer that sends user events to Kafka.

### Basic Producer Example

```javascript
const { kafka } = require('./kafkaConfig')

async function produceUserEvent(userId, action, data) {
  const producer = kafka.producer()
  
  try {
    // Connect to Kafka
    await producer.connect()
    console.log('Producer connected')
    
    // Send message
    const result = await producer.send({
      topic: 'user-events',
      messages: [{
        key: userId, // Ensures same user goes to same partition
        value: JSON.stringify({
          userId,
          action,
          data,
          timestamp: new Date().toISOString()
        }),
        headers: {
          'source': 'user-service',
          'version': '1.0'
        }
      }]
    })
    
    console.log('Message sent:', result)
    return result
  } catch (error) {
    console.error('Error producing message:', error)
    throw error
  } finally {
    // Always disconnect
    await producer.disconnect()
  }
}

// Usage
async function main() {
  try {
    await produceUserEvent('user-123', 'login', {
      ip: '192.168.1.100',
      userAgent: 'Mozilla/5.0...'
    })
    
    await produceUserEvent('user-456', 'purchase', {
      productId: 'prod-789',
      amount: 29.99
    })
  } catch (error) {
    console.error('Failed to send events:', error)
  }
}

main()
```

### Understanding the Send Result

```javascript
{
  topicName: 'user-events',
  partition: 0,
  errorCode: 0,
  offset: 123,
  timestamp: '1634567890123',
  baseOffset: '-1',
  logAppendTime: '-1',
  logStartOffset: '0'
}
```

**Key fields:**
- `partition`: Which partition the message went to
- `offset`: Position within that partition
- `errorCode`: 0 = success, non-zero = error

### Producer with Error Handling

```javascript
const { Kafka } = require('kafkajs')

const kafka = new Kafka({
  clientId: 'robust-producer',
  brokers: ['localhost:9092'],
  retry: {
    initialRetryTime: 100,
    retries: 8
  }
})

const producer = kafka.producer({
  // Transactional producer
  transactionalId: 'user-events-producer',
  maxInFlightRequests: 1,
  idempotent: true, // Prevent duplicates
  // Custom partitioner
  createPartitioner: ({ topic, partitionMetadata, message }) => {
    // Custom logic for partition selection
    const numPartitions = partitionMetadata.length
    const key = message.key ? message.key.toString() : ''
    return key.charCodeAt(0) % numPartitions
  }
})

producer.on('producer.connect', () => {
  console.log('Producer connected')
})

producer.on('producer.disconnect', () => {
  console.log('Producer disconnected')
})

producer.on('producer.network.request_timeout', (payload) => {
  console.error('Request timeout:', payload)
})

async function sendWithRetry(message) {
  try {
    await producer.connect()
    
    const result = await producer.send({
      topic: 'user-events',
      messages: [message]
    })
    
    console.log('Message delivered:', result)
    return result
  } catch (error) {
    if (error.name === 'KafkaJSNonRetriableError') {
      console.error('Non-retriable error:', error)
      throw error
    }
    
    console.error('Retriable error, will retry:', error)
    throw error // KafkaJS will retry based on configuration
  }
}
```

---

## Your First KafkaJS Consumer {#first-consumer}

Now let's build a consumer to process the user events we're producing.

### Basic Consumer Example

```javascript
const { kafka } = require('./kafkaConfig')

async function consumeUserEvents() {
  const consumer = kafka.consumer({ 
    groupId: 'user-event-processors',
    // Allow starting from beginning if no offset committed
    sessionTimeout: 30000,
    heartbeatInterval: 3000
  })
  
  try {
    // Connect to Kafka
    await consumer.connect()
    console.log('Consumer connected')
    
    // Subscribe to topic
    await consumer.subscribe({
      topic: 'user-events',
      fromBeginning: false // Start from latest committed offset
    })
    console.log('Subscribed to user-events')
    
    // Process messages
    await consumer.run({
      eachMessage: async ({ topic, partition, message }) => {
        try {
          const event = JSON.parse(message.value.toString())
          console.log(`Received event from ${topic}[${partition}]:`, event)
          
          // Process the event
          await processUserEvent(event)
          
          console.log(`Processed event for user ${event.userId}`)
        } catch (error) {
          console.error('Error processing message:', error)
          // Decide whether to commit or not based on error type
          throw error // This will cause message to be reprocessed
        }
      },
      
      // Optional: Process batches
      eachBatch: async ({ batch, resolveOffset, heartbeat, isRunning, isStale }) => {
        console.log(`Processing batch of ${batch.messages.length} messages`)
        
        for (const message of batch.messages) {
          if (!isRunning() || isStale()) break
          
          const event = JSON.parse(message.value.toString())
          await processUserEvent(event)
          
          // Mark this message as processed
          resolveOffset(message.offset)
          
          // Send heartbeat to prevent rebalance
          await heartbeat()
        }
      }
    })
  } catch (error) {
    console.error('Consumer error:', error)
    throw error
  }
}

async function processUserEvent(event) {
  switch (event.action) {
    case 'login':
      console.log(`User ${event.userId} logged in from ${event.data.ip}`)
      // Update user activity in database
      break
      
    case 'purchase':
      console.log(`User ${event.userId} purchased ${event.data.productId} for $${event.data.amount}`)
      // Process payment, update inventory, etc.
      break
      
    default:
      console.log(`Unknown event type: ${event.action}`)
  }
}

// Graceful shutdown
process.on('SIGINT', async () => {
  console.log('Shutting down consumer...')
  await consumer.disconnect()
  process.exit(0)
})

consumeUserEvents().catch(console.error)
```

### Consumer with Manual Offset Management

```javascript
const consumer = kafka.consumer({ 
  groupId: 'manual-offset-consumer',
  // Disable auto-commit to control exactly when offsets are committed
  enableAutoCommit: false
})

await consumer.run({
  eachMessage: async ({ topic, partition, message, heartbeat }) => {
    try {
      const event = JSON.parse(message.value.toString())
      
      // Process with business logic
      await processWithRetry(event)
      
      // Manually commit offset after successful processing
      await consumer.commitOffsets([
        { topic, partition, offset: message.offset + 1 }
      ])
      
      console.log(`Committed offset ${message.offset + 1} for ${topic}[${partition}]`)
    } catch (error) {
      console.error('Processing failed, not committing offset:', error)
      // Don't commit - message will be reprocessed
    }
  }
})
```

### Consumer with Multiple Topics

```javascript
await consumer.subscribe({
  topics: ['user-events', 'order-events', 'payment-events'],
  fromBeginning: false
})

await consumer.run({
  eachMessage: async ({ topic, partition, message }) => {
    const event = JSON.parse(message.value.toString())
    
    // Route to appropriate handler based on topic
    switch (topic) {
      case 'user-events':
        await handleUserEvent(event)
        break
      case 'order-events':
        await handleOrderEvent(event)
        break
      case 'payment-events':
        await handlePaymentEvent(event)
        break
      default:
        console.log(`Unknown topic: ${topic}`)
    }
  }
})
```

---

## Advanced Producer Patterns {#advanced-producer}

### Transactional Producer

Transactional producers ensure atomicity across multiple topics:

```javascript
const producer = kafka.producer({
  transactionalId: 'order-processor',
  maxInFlightRequests: 1,
  idempotent: true
})

async function processOrder(order) {
  const transaction = await producer.transaction()
  
  try {
    // Send order created event
    await transaction.send({
      topic: 'order-events',
      messages: [{
        key: order.id,
        value: JSON.stringify({
          orderId: order.id,
          status: 'created',
          timestamp: new Date().toISOString()
        })
      }]
    })
    
    // Update inventory
    await transaction.send({
      topic: 'inventory-events',
      messages: [{
        key: order.productId,
        value: JSON.stringify({
          productId: order.productId,
          quantity: -order.quantity,
          orderId: order.id
        })
      }]
    })
    
    // Reserve payment
    await transaction.send({
      topic: 'payment-events',
      messages: [{
        key: order.userId,
        value: JSON.stringify({
          userId: order.userId,
          amount: order.total,
          orderId: order.id,
          action: 'reserve'
        })
      }]
    })
    
    // Commit transaction - all messages become visible atomically
    await transaction.commit()
    console.log(`Order ${order.id} processed successfully`)
    
  } catch (error) {
    console.error('Error processing order, aborting transaction:', error)
    
    // Abort transaction - no messages become visible
    await transaction.abort()
    throw error
  }
}
```

### Batch Producer

For high throughput, send messages in batches:

```javascript
class BatchProducer {
  constructor() {
    this.producer = kafka.producer({
      maxInFlightRequests: 5,
      idempotent: true
    })
    this.batch = []
    this.batchSize = 100
    this.flushInterval = 1000 // 1 second
    this.flushTimer = null
  }
  
  async start() {
    await this.producer.connect()
    this.scheduleFlush()
  }
  
  async add(message) {
    this.batch.push(message)
    
    if (this.batch.length >= this.batchSize) {
      await this.flush()
    }
  }
  
  scheduleFlush() {
    if (this.flushTimer) clearTimeout(this.flushTimer)
    
    this.flushTimer = setTimeout(async () => {
      if (this.batch.length > 0) {
        await this.flush()
      }
      this.scheduleFlush()
    }, this.flushInterval)
  }
  
  async flush() {
    if (this.batch.length === 0) return
    
    const messagesToSend = this.batch.splice(0)
    
    try {
      const result = await this.producer.send({
        topic: 'high-volume-events',
        messages: messagesToSend
      })
      
      console.log(`Sent batch of ${messagesToSend.length} messages`)
      return result
    } catch (error) {
      console.error('Error sending batch:', error)
      // Re-add failed messages to batch
      this.batch.unshift(...messagesToSend)
      throw error
    }
  }
  
  async stop() {
    if (this.flushTimer) clearTimeout(this.flushTimer)
    await this.flush()
    await this.producer.disconnect()
  }
}

// Usage
const batchProducer = new BatchProducer()
await batchProducer.start()

// Add messages (they'll be batched automatically)
await batchProducer.add({ key: '1', value: 'message1' })
await batchProducer.add({ key: '2', value: 'message2' })
```

### Compression and Performance

```javascript
const producer = kafka.producer({
  // Compression reduces network bandwidth
  compression: CompressionTypes.GZIP, // or NONE, SNAPPY, LZ4, ZSTD
  
  // Batch configuration
  batchMaxMessages: 1000,
  batchMaxBytes: 1024 * 1024, // 1MB
  batchTimeout: 1000, // 1 second
  
  // Connection pooling
  connectionTimeout: 10000,
  requestTimeout: 30000,
  
  // Retry strategy
  retry: {
    initialRetryTime: 100,
    retries: 10,
    factor: 2,
    multiplier: 2
  }
})

// Monitor producer metrics
producer.on('producer.events', (event) => {
  if (event.type === 'producer.send.batch.size') {
    console.log('Batch size:', event.payload.batchSize)
  }
})
```

---

## Advanced Consumer Patterns {#advanced-consumer}

### Dynamic Topic Subscription

```javascript
class DynamicConsumer {
  constructor(groupId) {
    this.consumer = kafka.consumer({ groupId })
    this.subscribedTopics = new Set()
  }
  
  async start() {
    await this.consumer.connect()
    
    // Monitor for new topics
    setInterval(async () => {
      await this.checkForNewTopics()
    }, 30000) // Check every 30 seconds
    
    await this.consumer.run({
      eachMessage: async ({ topic, partition, message }) => {
        await this.processMessage(topic, message)
      }
    })
  }
  
  async checkForNewTopics() {
    const admin = kafka.admin()
    await admin.connect()
    
    const topicMetadata = await admin.fetchTopicMetadata()
    const availableTopics = topicMetadata.topics.map(t => t.name)
    
    const newTopics = availableTopics.filter(
      topic => topic.startsWith('user-') && !this.subscribedTopics.has(topic)
    )
    
    if (newTopics.length > 0) {
      console.log('Found new topics:', newTopics)
      
      for (const topic of newTopics) {
        await this.consumer.subscribe({ topic })
        this.subscribedTopics.add(topic)
      }
    }
    
    await admin.disconnect()
  }
  
  async processMessage(topic, message) {
    const event = JSON.parse(message.value.toString())
    console.log(`Processing ${event.type} from ${topic}`)
    // Process based on topic pattern
  }
}
```

### Consumer with Exactly-Once Processing

```javascript
class ExactlyOnceConsumer {
  constructor(groupId) {
    this.consumer = kafka.consumer({
      groupId,
      // Read uncommitted messages
      isolationLevel: 'read_committed',
      // Disable auto-commit for manual control
      enableAutoCommit: false
    })
    this.processedOffsets = new Map() // topic-partition -> offset
  }
  
  async start() {
    await this.consumer.connect()
    await this.consumer.subscribe({ topic: 'critical-events' })
    
    await this.consumer.run({
      eachMessage: async ({ topic, partition, message }) => {
        const key = `${topic}-${partition}`
        const offset = message.offset
        
        // Check if already processed
        const lastProcessed = this.processedOffsets.get(key) || -1
        if (offset <= lastProcessed) {
          console.log(`Skipping already processed message ${offset}`)
          return
        }
        
        try {
          // Process with idempotent handler
          await this.processIdempotently(message)
          
          // Update processed offset
          this.processedOffsets.set(key, offset)
          
          // Commit offset
          await this.consumer.commitOffsets([
            { topic, partition, offset: offset + 1 }
          ])
          
          console.log(`Processed and committed offset ${offset}`)
        } catch (error) {
          console.error('Processing failed:', error)
          // Don't commit - message will be reprocessed
          throw error
        }
      }
    })
  }
  
  async processIdempotently(message) {
    const event = JSON.parse(message.value.toString())
    
    // Use database unique constraints or external storage
    // to ensure idempotency
    const result = await db.events.upsert({
      where: { eventId: event.id },
      update: { processedAt: new Date() },
      create: {
        eventId: event.id,
        eventData: event,
        processedAt: new Date()
      }
    })
    
    if (result.created) {
      // First time processing this event
      await this.handleNewEvent(event)
    } else {
      console.log(`Event ${event.id} already processed`)
    }
  }
}
```

### Consumer with Backpressure Control

```javascript
class BackpressureConsumer {
  constructor(groupId) {
    this.consumer = kafka.consumer({ groupId })
    this.processing = 0
    this.maxConcurrent = 10
    this.queue = []
  }
  
  async start() {
    await this.consumer.connect()
    await this.consumer.subscribe({ topic: 'high-volume-events' })
    
    await this.consumer.run({
      eachMessage: async ({ topic, partition, message }) => {
        // Wait if too many concurrent processes
        while (this.processing >= this.maxConcurrent) {
          await this.sleep(100)
        }
        
        this.processing++
        
        // Process asynchronously
        this.processMessage(message)
          .finally(() => {
            this.processing--
          })
      }
    })
  }
  
  async processMessage(message) {
    try {
      const event = JSON.parse(message.value.toString())
      
      // Simulate processing time
      await this.processEvent(event)
      
      // Commit after successful processing
      await this.consumer.commitOffsets([
        { 
          topic: message.topic, 
          partition: message.partition, 
          offset: message.offset + 1 
        }
      ])
    } catch (error) {
      console.error('Processing error:', error)
      // Implement retry logic or dead letter queue
    }
  }
  
  async processEvent(event) {
    // Your business logic here
    // Add artificial delay for demonstration
    await this.sleep(Math.random() * 1000)
    console.log(`Processed event ${event.id}`)
  }
  
  sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms))
  }
}
```

---

## Schema Management and Serialization {#schema-management}

### JSON Schema Validation

```javascript
const Ajv = require('ajv')
const addFormats = require('ajv-formats')

const ajv = new Ajv()
addFormats(ajv)

// Define schemas
const schemas = {
  'user-events': {
    type: 'object',
    properties: {
      userId: { type: 'string', format: 'uuid' },
      action: { type: 'string', enum: ['login', 'logout', 'register'] },
      timestamp: { type: 'string', format: 'date-time' },
      data: { type: 'object' }
    },
    required: ['userId', 'action', 'timestamp'],
    additionalProperties: false
  },
  
  'order-events': {
    type: 'object',
    properties: {
      orderId: { type: 'string' },
      userId: { type: 'string' },
      total: { type: 'number', minimum: 0 },
      items: {
        type: 'array',
        items: {
          type: 'object',
          properties: {
            productId: { type: 'string' },
            quantity: { type: 'integer', minimum: 1 },
            price: { type: 'number', minimum: 0 }
          },
          required: ['productId', 'quantity', 'price']
        }
      }
    },
    required: ['orderId', 'userId', 'total', 'items']
  }
}

// Validate on producer side
function validateAndProduce(topic, event) {
  const validate = ajv.compile(schemas[topic])
  
  if (!validate(event)) {
    throw new Error(`Invalid event: ${JSON.stringify(validate.errors)}`)
  }
  
  return producer.send({
    topic,
    messages: [{
      key: event.userId || event.orderId,
      value: JSON.stringify(event),
      headers: {
        'schema-version': '1.0',
        'content-type': 'application/json'
      }
    }]
  })
}

// Validate on consumer side
async function consumeWithValidation() {
  await consumer.run({
    eachMessage: async ({ topic, message }) => {
      try {
        const event = JSON.parse(message.value.toString())
        
        // Validate against schema
        const validate = ajv.compile(schemas[topic])
        if (!validate(event)) {
          console.error(`Invalid event received: ${JSON.stringify(validate.errors)}`)
          // Send to dead letter queue or error topic
          await sendToErrorTopic(message, validate.errors)
          return
        }
        
        await processValidEvent(event)
      } catch (error) {
        console.error('Error processing message:', error)
      }
    }
  })
}
```

### Avro Serialization

```javascript
const avro = require('avsc')

// Define Avro schema
const userEventSchema = avro.Type.forSchema({
  type: 'record',
  name: 'UserEvent',
  fields: [
    { name: 'userId', type: 'string' },
    { name: 'action', type: { type: 'enum', symbols: ['login', 'logout', 'register'] } },
    { name: 'timestamp', type: 'long', logicalType: 'timestamp-millis' },
    { name: 'data', type: ['null', 'map'], default: null }
  ]
})

// Producer with Avro
async function produceAvroEvent(event) {
  // Validate and encode
  const buffer = userEventSchema.toBuffer(event)
  
  await producer.send({
    topic: 'user-events-avro',
    messages: [{
      key: event.userId,
      value: buffer,
      headers: {
        'content-type': 'application/avro',
        'schema-id': 'user-event-v1'
      }
    }]
  })
}

// Consumer with Avro
await consumer.run({
  eachMessage: async ({ message }) => {
    try {
      // Decode Avro message
      const event = userEventSchema.fromBuffer(message.value)
      
      console.log('Received Avro event:', event)
      await processEvent(event)
    } catch (error) {
      console.error('Error decoding Avro message:', error)
    }
  }
})
```

### Schema Registry Integration

```javascript
const { SchemaRegistry } = require('@kafkajs/confluent-schema-registry')

const registry = new SchemaRegistry({
  host: 'http://localhost:8081', // Schema Registry URL
  auth: {
    username: process.env.SCHEMA_REGISTRY_USERNAME,
    password: process.env.SCHEMA_REGISTRY_PASSWORD
  }
})

// Register schema
async function registerSchema(topic, schema) {
  const { id } = await registry.register({
    type: SchemaRegistry.AVRO,
    schema: JSON.stringify(schema)
  })
  
  console.log(`Schema registered with ID: ${id}`)
  return id
}

// Producer with Schema Registry
async function produceWithSchema(topic, event) {
  const schemaId = await registerSchema(topic, schemas[topic])
  
  // Encode with schema ID
  const encoded = await registry.encode(schemaId, event)
  
  await producer.send({
    topic,
    messages: [{
      key: event.userId,
      value: encoded
    }]
  })
}

// Consumer with Schema Registry
await consumer.run({
  eachMessage: async ({ message }) => {
    try {
      // Decode using schema registry
      const event = await registry.decode(message.value)
      
      console.log('Decoded event:', event)
      await processEvent(event)
    } catch (error) {
      console.error('Error decoding message:', error)
    }
  }
})
```

---

## Error Handling and Resilience {#error-handling}

### Dead Letter Queue Pattern

```javascript
class DLQConsumer {
  constructor(groupId) {
    this.consumer = kafka.consumer({ groupId })
    this.producer = kafka.producer()
    this.dlqTopic = 'dead-letter-queue'
  }
  
  async start() {
    await this.consumer.connect()
    await this.producer.connect()
    
    await this.consumer.subscribe({ topic: 'main-events' })
    
    await this.consumer.run({
      eachMessage: async ({ topic, partition, message }) => {
        try {
          await this.processMessage(message)
          
          // Commit on success
          await this.consumer.commitOffsets([
            { topic, partition, offset: message.offset + 1 }
          ])
        } catch (error) {
          console.error('Processing failed:', error)
          
          // Send to DLQ
          await this.sendToDLQ(message, error)
          
          // Still commit to avoid infinite retries
          await this.consumer.commitOffsets([
            { topic, partition, offset: message.offset + 1 }
          ])
        }
      }
    })
  }
  
  async sendToDLQ(originalMessage, error) {
    const dlqMessage = {
      key: originalMessage.key,
      value: JSON.stringify({
        originalMessage: originalMessage.value.toString(),
        error: {
          message: error.message,
          stack: error.stack,
          timestamp: new Date().toISOString()
        },
        metadata: {
          originalTopic: originalMessage.topic,
          originalPartition: originalMessage.partition,
          originalOffset: originalMessage.offset,
          failedAt: new Date().toISOString()
        }
      }),
      headers: {
        ...originalMessage.headers,
        'dlq-reason': error.message,
        'dlq-timestamp': new Date().toISOString()
      }
    }
    
    await this.producer.send({
      topic: this.dlqTopic,
      messages: [dlqMessage]
    })
    
    console.log(`Message sent to DLQ: ${originalMessage.offset}`)
  }
}
```

### Circuit Breaker Pattern

```javascript
class CircuitBreakerConsumer {
  constructor(groupId) {
    this.consumer = kafka.consumer({ groupId })
    this.circuitState = 'CLOSED' // CLOSED, OPEN, HALF_OPEN
    this.failureCount = 0
    this.failureThreshold = 5
    this.recoveryTimeout = 60000 // 1 minute
    this.lastFailureTime = null
  }
  
  async start() {
    await this.consumer.connect()
    await this.consumer.subscribe({ topic: 'risky-events' })
    
    await this.consumer.run({
      eachMessage: async ({ topic, partition, message }) => {
        if (this.circuitState === 'OPEN') {
          if (this.shouldAttemptReset()) {
            this.circuitState = 'HALF_OPEN'
          } else {
            console.log('Circuit breaker OPEN - skipping message')
            return
          }
        }
        
        try {
          await this.processMessage(message)
          this.onSuccess()
        } catch (error) {
          this.onFailure()
          throw error
        }
      }
    })
  }
  
  async processMessage(message) {
    const event = JSON.parse(message.value.toString())
    
    // Simulate potentially failing operation
    if (Math.random() < 0.3) { // 30% failure rate
      throw new Error('Simulated processing failure')
    }
    
    console.log('Successfully processed:', event)
  }
  
  onSuccess() {
    this.failureCount = 0
    if (this.circuitState === 'HALF_OPEN') {
      console.log('Circuit breaker CLOSED - recovery successful')
      this.circuitState = 'CLOSED'
    }
  }
  
  onFailure() {
    this.failureCount++
    this.lastFailureTime = Date.now()
    
    if (this.failureCount >= this.failureThreshold) {
      console.log('Circuit breaker OPEN - too many failures')
      this.circuitState = 'OPEN'
    }
  }
  
  shouldAttemptReset() {
    return Date.now() - this.lastFailureTime > this.recoveryTimeout
  }
}
```

### Retry with Exponential Backoff

```javascript
class RetryConsumer {
  constructor(groupId) {
    this.consumer = kafka.consumer({ groupId })
    this.retryTopic = 'retry-queue'
    this.producer = kafka.producer()
  }
  
  async start() {
    await this.consumer.connect()
    await this.producer.connect()
    
    // Subscribe to both main and retry topics
    await this.consumer.subscribe({
      topics: ['main-events', 'retry-queue']
    })
    
    await this.consumer.run({
      eachMessage: async ({ topic, partition, message }) => {
        try {
          if (topic === 'retry-queue') {
            await this.processRetryMessage(message)
          } else {
            await this.processMainMessage(message)
          }
        } catch (error) {
          await this.handleFailure(topic, message, error)
        }
      }
    })
  }
  
  async processRetryMessage(message) {
    const retryEvent = JSON.parse(message.value.toString())
    const { originalMessage, retryCount, nextRetryAt } = retryEvent
    
    // Check if it's time to retry
    if (Date.now() < nextRetryAt) {
      // Re-queue for later
      await this.producer.send({
        topic: this.retryTopic,
        messages: [message]
      })
      return
    }
    
    // Process the original message
    const originalMsg = {
      ...message,
      value: originalMessage
    }
    
    await this.processMainMessage(originalMsg)
  }
  
  async handleFailure(topic, message, error) {
    if (topic === 'retry-queue') {
      // Already in retry queue - send to DLQ
      await this.sendToDLQ(message, error)
      return
    }
    
    const headers = message.headers || {}
    const retryCount = parseInt(headers['retry-count'] || '0')
    
    if (retryCount >= 3) {
      // Max retries reached - send to DLQ
      await this.sendToDLQ(message, error)
      return
    }
    
    // Calculate next retry time with exponential backoff
    const delay = Math.pow(2, retryCount) * 1000 // 2^n seconds
    const nextRetryAt = Date.now() + delay
    
    // Send to retry queue
    await this.producer.send({
      topic: this.retryTopic,
      messages: [{
        key: message.key,
        value: JSON.stringify({
          originalMessage: message.value.toString(),
          retryCount: retryCount + 1,
          nextRetryAt,
          lastError: error.message
        }),
        headers: {
          ...headers,
          'retry-count': (retryCount + 1).toString()
        }
      }]
    })
    
    console.log(`Message scheduled for retry #${retryCount + 1} in ${delay}ms`)
  }
}
```

---

## Performance Optimization {#performance}

### Consumer Optimization

```javascript
class OptimizedConsumer {
  constructor(groupId) {
    this.consumer = kafka.consumer({
      groupId,
      // Fetch larger batches
      minBytes: 1024 * 1024, // 1MB
      maxBytes: 10 * 1024 * 1024, // 10MB
      maxWaitTimeInMs: 5000, // Wait up to 5 seconds
      
      // Optimize for throughput
      sessionTimeout: 30000,
      heartbeatInterval: 3000,
      
      // Read only committed messages (exactly-once)
      isolationLevel: 'read_committed'
    })
  }
  
  async start() {
    await this.consumer.connect()
    await this.consumer.subscribe({ topic: 'high-volume-events' })
    
    await this.consumer.run({
      // Process batches for better throughput
      eachBatch: async ({ batch, resolveOffset, heartbeat, isRunning }) => {
        const startTime = Date.now()
        
        // Process messages in parallel within the batch
        const promises = batch.messages.map(async (message) => {
          try {
            await this.processMessageFast(message)
            return { success: true, message }
          } catch (error) {
            console.error('Error processing message:', error)
            return { success: false, message, error }
          }
        })
        
        const results = await Promise.allSettled(promises)
        
        // Commit only successfully processed messages
        for (let i = 0; i < results.length; i++) {
          const result = results[i]
          if (result.status === 'fulfilled' && result.value.success) {
            resolveOffset(batch.messages[i].offset)
          }
          
          // Send heartbeat periodically
          if (i % 10 === 0) {
            await heartbeat()
          }
          
          if (!isRunning()) break
        }
        
        const duration = Date.now() - startTime
        console.log(`Processed batch of ${batch.messages.length} messages in ${duration}ms`)
      }
    })
  }
  
  async processMessageFast(message) {
    const event = JSON.parse(message.value.toString())
    
    // Use connection pooling for database operations
    const dbConnection = await this.getConnection()
    
    try {
      // Batch database operations
      await dbConnection.insert('events', [event])
    } finally {
      this.releaseConnection(dbConnection)
    }
  }
}
```

### Producer Optimization

```javascript
class OptimizedProducer {
  constructor() {
    this.producer = kafka.producer({
      // Enable idempotence for exactly-once
      idempotent: true,
      
      // Compression settings
      compression: CompressionTypes.GZIP,
      
      // Batching for throughput
      batchMaxMessages: 10000,
      batchMaxBytes: 10 * 1024 * 1024, // 10MB
      batchTimeout: 100, // 100ms
      
      // Connection settings
      maxInFlightRequests: 5,
      requestTimeout: 30000,
      
      // Retry configuration
      retry: {
        initialRetryTime: 100,
        retries: 10,
        factor: 2
      }
    })
    
    this.messageBuffer = []
    this.flushInterval = 100
    this.maxBufferSize = 1000
  }
  
  async start() {
    await this.producer.connect()
    this.startBatching()
  }
  
  startBatching() {
    setInterval(async () => {
      if (this.messageBuffer.length > 0) {
        await this.flushBuffer()
      }
    }, this.flushInterval)
  }
  
  async send(message) {
    this.messageBuffer.push(message)
    
    if (this.messageBuffer.length >= this.maxBufferSize) {
      await this.flushBuffer()
    }
  }
  
  async flushBuffer() {
    if (this.messageBuffer.length === 0) return
    
    const messages = this.messageBuffer.splice(0)
    
    try {
      // Group by topic for efficiency
      const messagesByTopic = messages.reduce((acc, msg) => {
        if (!acc[msg.topic]) acc[msg.topic] = []
        acc[msg.topic].push(msg)
        return acc
      }, {})
      
      // Send to each topic
      for (const [topic, topicMessages] of Object.entries(messagesByTopic)) {
        await this.producer.send({
          topic,
          messages: topicMessages.map(msg => ({
            key: msg.key,
            value: msg.value,
            headers: msg.headers,
            timestamp: Date.now()
          }))
        })
      }
      
      console.log(`Flushed ${messages.length} messages`)
    } catch (error) {
      console.error('Error flushing buffer:', error)
      // Re-add messages to buffer for retry
      this.messageBuffer.unshift(...messages)
    }
  }
}
```

### Monitoring and Metrics

```javascript
class MonitoredConsumer {
  constructor(groupId) {
    this.consumer = kafka.consumer({ groupId })
    this.metrics = {
      messagesProcessed: 0,
      errors: 0,
      processingTimes: [],
      lastReset: Date.now()
    }
  }
  
  async start() {
    await this.consumer.connect()
    await this.consumer.subscribe({ topic: 'monitored-events' })
    
    // Start metrics reporting
    setInterval(() => this.reportMetrics(), 60000) // Every minute
    
    await this.consumer.run({
      eachMessage: async ({ message }) => {
        const startTime = Date.now()
        
        try {
          await this.processMessage(message)
          
          const processingTime = Date.now() - startTime
          this.metrics.messagesProcessed++
          this.metrics.processingTimes.push(processingTime)
          
        } catch (error) {
          this.metrics.errors++
          console.error('Processing error:', error)
        }
      }
    })
  }
  
  reportMetrics() {
    const now = Date.now()
    const duration = (now - this.metrics.lastReset) / 1000 // seconds
    
    const avgProcessingTime = this.metrics.processingTimes.length > 0
      ? this.metrics.processingTimes.reduce((a, b) => a + b, 0) / this.metrics.processingTimes.length
      : 0
    
    const throughput = this.metrics.messagesProcessed / duration
    
    console.log('=== Consumer Metrics ===')
    console.log(`Duration: ${duration}s`)
    console.log(`Messages processed: ${this.metrics.messagesProcessed}`)
    console.log(`Errors: ${this.metrics.errors}`)
    console.log(`Throughput: ${throughput.toFixed(2)} msg/s`)
    console.log(`Avg processing time: ${avgProcessingTime.toFixed(2)}ms`)
    console.log('========================')
    
    // Reset metrics
    this.metrics = {
      messagesProcessed: 0,
      errors: 0,
      processingTimes: [],
      lastReset: now
    }
  }
}
```

---

## Production Deployment {#production}

### Production Configuration

```javascript
// kafkaConfig.prod.js
const { Kafka, CompressionTypes } = require('kafkajs')
const fs = require('fs')

const isProduction = process.env.NODE_ENV === 'production'

const kafkaConfig = {
  clientId: process.env.KAFKA_CLIENT_ID || 'my-app',
  brokers: process.env.KAFKA_BROKERS?.split(',') || ['localhost:9092'],
  
  // SSL configuration for production
  ssl: isProduction ? {
    rejectUnauthorized: true,
    ca: [fs.readFileSync(process.env.KAFKA_CA_PATH, 'utf-8')],
    key: fs.readFileSync(process.env.KAFKA_KEY_PATH, 'utf-8'),
    cert: fs.readFileSync(process.env.KAFKA_CERT_PATH, 'utf-8'),
    passphrase: process.env.KAFKA_CERT_PASSPHRASE
  } : false,
  
  // SASL authentication
  sasl: isProduction ? {
    mechanism: 'plain',
    username: process.env.KAFKA_USERNAME,
    password: process.env.KAFKA_PASSWORD
  } : undefined,
  
  // Connection settings
  connectionTimeout: 10000,
  requestTimeout: 30000,
  
  // Retry configuration
  retry: {
    initialRetryTime: 100,
    retries: 8,
    factor: 2,
    multiplier: 2
  }
}

const kafka = new Kafka(kafkaConfig)

// Producer configuration
const producerConfig = {
  // Enable idempotence for exactly-once delivery
  idempotent: true,
  maxInFlightRequests: 5,
  
  // Compression for network efficiency
  compression: CompressionTypes.GZIP,
  
  // Batching for throughput
  batchMaxMessages: 1000,
  batchMaxBytes: 1024 * 1024, // 1MB
  batchTimeout: 100,
  
  // Transaction support
  transactionalId: process.env.KAFKA_TRANSACTIONAL_ID,
  transactionTimeout: 60000 // 1 minute
}

// Consumer configuration
const consumerConfig = {
  sessionTimeout: 30000,
  heartbeatInterval: 3000,
  
  // Exactly-once semantics
  enableAutoCommit: false,
  isolationLevel: 'read_committed',
  
  // Performance tuning
  minBytes: 1024 * 1024, // 1MB
  maxBytes: 10 * 1024 * 1024, // 10MB
  maxWaitTimeInMs: 5000,
  
  // Rebalance configuration
  rebalanceTimeout: 60000,
  maxBytesPerPartition: 1048576 // 1MB
}

module.exports = {
  kafka,
  producerConfig,
  consumerConfig
}
```

### Health Check Service

```javascript
class KafkaHealthCheck {
  constructor() {
    this.admin = kafka.admin()
    this.producer = kafka.producer()
    this.consumer = kafka.consumer({ 
      groupId: 'health-check-group' 
    })
  }
  
  async checkHealth() {
    const health = {
      status: 'healthy',
      checks: {},
      timestamp: new Date().toISOString()
    }
    
    try {
      // Check admin connection
      await this.admin.connect()
      const metadata = await this.admin.fetchTopicMetadata()
      health.checks.admin = {
        status: 'healthy',
        topicsCount: metadata.topics.length
      }
      await this.admin.disconnect()
    } catch (error) {
      health.checks.admin = {
        status: 'unhealthy',
        error: error.message
      }
      health.status = 'unhealthy'
    }
    
    try {
      // Check producer
      await this.producer.connect()
      health.checks.producer = {
        status: 'healthy'
      }
      await this.producer.disconnect()
    } catch (error) {
      health.checks.producer = {
        status: 'unhealthy',
        error: error.message
      }
      health.status = 'unhealthy'
    }
    
    try {
      // Check consumer
      await this.consumer.connect()
      health.checks.consumer = {
        status: 'healthy'
      }
      await this.consumer.disconnect()
    } catch (error) {
      health.checks.consumer = {
        status: 'unhealthy',
        error: error.message
      }
      health.status = 'unhealthy'
    }
    
    return health
  }
}

// Express health endpoint
const express = require('express')
const app = express()
const healthCheck = new KafkaHealthCheck()

app.get('/health', async (req, res) => {
  const health = await healthCheck.checkHealth()
  const statusCode = health.status === 'healthy' ? 200 : 503
  res.status(statusCode).json(health)
})

app.listen(3000, () => {
  console.log('Health check service listening on port 3000')
})
```

### Graceful Shutdown

```javascript
class GracefulKafkaService {
  constructor() {
    this.producer = kafka.producer(producerConfig)
    this.consumer = kafka.consumer(consumerConfig)
    this.isShuttingDown = false
  }
  
  async start() {
    // Set up graceful shutdown handlers
    process.on('SIGTERM', () => this.shutdown('SIGTERM'))
    process.on('SIGINT', () => this.shutdown('SIGINT'))
    
    await this.producer.connect()
    await this.consumer.connect()
    await this.consumer.subscribe({ topic: 'events' })
    
    await this.consumer.run({
      eachMessage: async ({ topic, partition, message }) => {
        if (this.isShuttingDown) {
          console.log('Shutdown in progress, skipping message')
          return
        }
        
        try {
          await this.processMessage(message)
          
          // Commit offset
          await this.consumer.commitOffsets([
            { topic, partition, offset: message.offset + 1 }
          ])
        } catch (error) {
          console.error('Error processing message:', error)
        }
      }
    })
    
    console.log('Service started successfully')
  }
  
  async shutdown(signal) {
    if (this.isShuttingDown) {
      console.log('Shutdown already in progress')
      return
    }
    
    this.isShuttingDown = true
    console.log(`\nReceived ${signal}. Starting graceful shutdown...`)
    
    try {
      // Stop consuming new messages
      await this.consumer.stop()
      console.log('Consumer stopped')
      
      // Wait for in-flight messages to complete
      await this.waitForInFlightMessages()
      
      // Disconnect producer (flushes any pending messages)
      await this.producer.disconnect()
      console.log('Producer disconnected')
      
      // Disconnect consumer
      await this.consumer.disconnect()
      console.log('Consumer disconnected')
      
      console.log('Graceful shutdown completed')
      process.exit(0)
    } catch (error) {
      console.error('Error during shutdown:', error)
      process.exit(1)
    }
  }
  
  async waitForInFlightMessages() {
    // Wait for any ongoing processing to complete
    const maxWaitTime = 30000 // 30 seconds
    const startTime = Date.now()
    
    while (Date.now() - startTime < maxWaitTime) {
      // Check if there are still messages being processed
      // This depends on your application's tracking mechanism
      if (this.getInFlightCount() === 0) {
        break
      }
      
      await this.sleep(1000)
    }
  }
  
  sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms))
  }
}
```

---

## Resources and Further Learning {#resources}

### Official Documentation

- **KafkaJS Documentation**: [kafkajs.org](https://kafkajs.org) - Comprehensive API reference and guides
- **Apache Kafka Documentation**: [kafka.apache.org/documentation](https://kafka.apache.org/documentation) - Official Kafka documentation
- **Confluent Documentation**: [docs.confluent.io](https://docs.confluent.io) - Enterprise Kafka resources

### Books and Courses

- **"Kafka: The Definitive Guide"** by Neha Narkhede, Gwen Shapira, and Todd Palino
- **"Designing Event-Driven Systems"** by Ben Stopford
- **"Kafka Streams in Action"** by Bill Bejeck
- **Confluent Developer Courses**: [confluent.io/developer-courses](https://confluent.io/developer-courses)

### Tools and Utilities

- **Kafka UI**: [provectuslabs/kafka-ui](https://github.com/provectuslabs/kafka-ui) - Web interface for Kafka
- **kcat**: [github.com/edenhill/kcat](https://github.com/edenhill/kcat) - Command line Kafka producer/consumer
- **Kafka Tools**: [linkedin/kafka-tools](https://github.com/linkedin/kafka-tools) - LinkedIn's Kafka utilities
- **Schema Registry UI**: [landoop/schema-registry-ui](https://github.com/landoop/schema-registry-ui)

### Testing and Development

- **Testcontainers**: [node-testcontainers](https://node-testcontainers.github.io/) - Integration testing with Kafka
- **kafkajs-unit**: [github.com/salsita/node-kafkajs-unit](https://github.com/salsita/node-kafkajs-unit) - Unit testing utilities
- **Mock Kafka**: [github.com/waldo/kafkajs-mock](https://github.com/waldo/kafkajs-mock) - Mock Kafka for testing

### Monitoring and Observability

- **Prometheus JMX Exporter**: [github.com/prometheus/jmx_exporter](https://github.com/prometheus/jmx_exporter)
- **Burrow**: [github.com/linkedin/Burrow](https://github.com/linkedin/Burrow) - Kafka consumer lag monitoring
- **Kafka Monitor**: [github.com/linkedin/kafka-monitor](https://github.com/linkedin/kafka-monitor) - LinkedIn's monitoring tools
- **Confluent Control Center**: Enterprise monitoring solution

### Advanced Topics

- **Kafka Streams**: Real-time stream processing
- **ksqlDB**: SQL interface for Kafka
- **Kafka Connect**: Integration with external systems
- **Exactly-Once Semantics**: Deep dive into transactional guarantees
- **Security**: SSL, SASL, and ACL configuration

### Community and Support

- **KafkaJS GitHub**: [github.com/tulios/kafkajs](https://github.com/tulios/kafkajs) - Source code and issues
- **Apache Kafka Mailing List**: [kafka.apache.org/contact](https://kafka.apache.org/contact) - Community support
- **Stack Overflow**: Tag `kafka` and `kafkajs`
- **Reddit**: r/apachekafka for discussions and help

### Example Projects

- **KafkaJS Examples**: [github.com/tulios/kafkajs/tree/master/examples](https://github.com/tulios/kafkajs/tree/master/examples)
- **Event Sourcing Example**: [github.com/evryfs/event-sourcing-examples](https://github.com/evryfs/event-sourcing-examples)
- **Microservices with Kafka**: [github.com/kbastani/kafka-microservices](https://github.com/kbastani/kafka-microservices)

### Performance Tuning Guides

- **LinkedIn Kafka Tuning**: [github.com/linkedin/kafka-tuning](https://github.com/linkedin/kafka-tuning)
- **Confluent Performance Tuning**: [docs.confluent.io/kafka/performance](https://docs.confluent.io/kafka/performance)
- **KafkaJS Best Practices**: [kafkajs.org/docs/faq](https://kafkajs.org/docs/faq)

### Quick Reference Cheatsheet

#### Producer Essentials
```javascript
// Basic producer
const producer = kafka.producer()
await producer.connect()

// Send message
await producer.send({
  topic: 'topic-name',
  messages: [{ key: 'key', value: 'value' }]
})

// Transactional producer
const tx = await producer.transaction()
await tx.send({ topic: 'topic', messages: [...] })
await tx.commit()

// Disconnect
await producer.disconnect()
```

#### Consumer Essentials
```javascript
// Basic consumer
const consumer = kafka.consumer({ groupId: 'group-name' })
await consumer.connect()
await consumer.subscribe({ topic: 'topic-name' })

// Run consumer
await consumer.run({
  eachMessage: async ({ message }) => {
    console.log(message.value.toString())
  }
})

// Manual offset commit
await consumer.commitOffsets([
  { topic: 'topic', partition: 0, offset: 123 }
])
```

#### Admin Operations
```javascript
const admin = kafka.admin()
await admin.connect()

// Create topic
await admin.createTopics({
  topics: [{
    topic: 'new-topic',
    numPartitions: 3,
    replicationFactor: 2
  }]
})

// List topics
const topics = await admin.listTopics()

// Delete topic
await admin.deleteTopics({ topics: ['old-topic'] })
```

---

## Conclusion

Congratulations! You've journeyed from Kafka basics to building production-ready event streaming applications with KafkaJS. 

**Key Takeaways:**
1. **Start Simple**: Master basic producer/consumer patterns before advanced features
2. **Embrace Batching**: Critical for performance in production
3. **Handle Errors Gracefully**: Implement DLQ, circuit breakers, and retries
4. **Monitor Everything**: Track metrics, lag, and system health
5. **Plan for Scale**: Design with partitioning and consumer groups in mind

**Your Next Steps:**
1. Set up a local Kafka cluster using Docker
2. Build a simple producer/consumer application
3. Implement schema management and validation
4. Add monitoring and error handling
5. Deploy to production with proper configuration

KafkaJS brings the power of Apache Kafka to the JavaScript ecosystem, enabling you to build robust, scalable event-driven systems. Now go build something amazing! 🚀

---

*Last Updated: December 3, 2025*
*KafkaJS Version: 2.2.4*
*Apache Kafka Version: 3.5.0*