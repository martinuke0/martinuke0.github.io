---
title: "When AI Models Disagree: Understanding Predictive Multiplicity in Medical AI"
date: "2026-03-25T01:00:18.796"
draft: false
tags: ["machine-learning", "medical-ai", "model-multiplicity", "predictive-uncertainty", "ai-reliability"]
---

## Table of Contents

1. [Introduction](#introduction)
2. [What is Model Multiplicity?](#what-is-model-multiplicity)
3. [The Medical Context: Why This Matters](#the-medical-context-why-this-matters)
4. [Understanding Predictive Multiplicity](#understanding-predictive-multiplicity)
5. [The Problem: Arbitrary Predictions from Equally Valid Models](#the-problem-arbitrary-predictions-from-equally-valid-models)
6. [Key Findings from Recent Research](#key-findings-from-recent-research)
7. [Real-World Implications](#real-world-implications)
8. [Solutions: Ensemble Methods and Beyond](#solutions-ensemble-methods-and-beyond)
9. [Key Concepts to Remember](#key-concepts-to-remember)
10. [The Future of Reliable Medical AI](#the-future-of-reliable-medical-ai)
11. [Resources](#resources)

## Introduction

Imagine you visit a doctor with concerning symptoms. The doctor runs a diagnostic test, and the result comes back positive for a serious condition. You're devastated. But here's the unsettling truth: if the doctor had used a slightly different diagnostic algorithm—one that performs just as well on all previous test cases—the result might have been negative. The diagnosis you received wasn't based on your actual symptoms or medical data alone; it was partly determined by arbitrary choices made when the algorithm was built.

This scenario isn't science fiction. It's the reality of **model multiplicity** in medical artificial intelligence, a phenomenon that recent research has brought into sharp focus. A groundbreaking study analyzing predictive multiplicity across medical tasks reveals that many machine learning models used in healthcare can produce conflicting predictions even when they're equally accurate and equally valid.[1][2][3]

This blog post explores what model multiplicity is, why it matters in medicine, and what we can do about it. Whether you're a healthcare professional, a data scientist, or simply curious about how AI impacts medical decisions, this deep dive will help you understand one of the most important challenges facing modern medical AI.

## What is Model Multiplicity?

Let's start with the basics. In machine learning, we train models to make predictions. A model is essentially a mathematical function that learns patterns from data. For a given prediction task—like predicting whether a patient has diabetes based on their medical history—there are usually many different models we could build that would perform equally well on test data.[1]

**Model multiplicity** refers to this phenomenon: the existence of multiple machine learning models that describe data equally well but may produce different predictions on individual samples.[1][2] Think of it like this: imagine you're trying to draw a line through a scatter plot of points. If the points form a loose cloud, there are many different lines you could draw that fit the data equally well. Each line represents a different valid model.

### Two Types of Multiplicity

Researchers have identified two distinct ways that models can differ despite having equal accuracy:[1]

**Procedural Multiplicity** occurs when models have equivalent accuracy but differ in their internal workings—the mathematical machinery under the hood. Two models might use completely different decision processes to arrive at the same overall accuracy. It's like two chefs using different recipes to create dishes that taste equally good.[1]

**Predictive Multiplicity** is more concerning for practical applications. This occurs when competing models achieve equal accuracy but make different predictions on specific individual cases.[2] This is where the real problem emerges: if two equally valid models disagree about your diagnosis, which one should we trust?

## The Medical Context: Why This Matters

Healthcare is perhaps the most consequential domain where AI is deployed. Unlike recommending a movie or predicting stock prices, an incorrect medical diagnosis can have life-altering consequences. A patient diagnosed with cancer when they don't have it faces unnecessary treatment and psychological trauma. A patient incorrectly cleared of cancer might miss critical early intervention.

This is why the existence of predictive multiplicity in medical AI is so troubling. Medical datasets are often limited compared to other domains. Diseases can be rare, making it harder to collect large amounts of training data. Patient populations vary widely, and what works for one group might not work equally well for another. These factors create the perfect conditions for multiple equally-valid models to exist.[1]

Moreover, healthcare professionals and patients expect AI systems to be reliable and defensible. When a doctor recommends a treatment, they should be able to explain why. If the recommendation comes from a model that's essentially arbitrary—chosen from among many equally valid alternatives—that undermines the legitimacy and trustworthiness of the entire system.

## Understanding Predictive Multiplicity

Let's dive deeper into predictive multiplicity, since that's the focus of the recent research we're discussing. Predictive multiplicity occurs when a prediction problem admits competing models that perform almost equally well but assign conflicting predictions to the same samples.[2]

### Measuring Predictive Multiplicity

Researchers have developed ways to quantify how severe predictive multiplicity is. Two key measures are:[4]

**Ambiguity** represents the proportion of samples where competing models make different predictions. If you have 100 patients and 10 of them receive different diagnoses from two equally-valid models, the ambiguity is 10%. This tells you what fraction of predictions are essentially arbitrary.

**Discrepancy** measures how different the predictions can be across competing models. It captures the maximum deviation in predictions across the set of equally-valid models.

These measures help researchers understand not just whether predictive multiplicity exists, but how severe it is in practice. A small amount of multiplicity might be acceptable; widespread multiplicity is a serious problem.

### Why Does Predictive Multiplicity Occur?

The root cause of predictive multiplicity lies in how machine learning works. When we train a model, we're trying to find a function that minimizes error on training data. But here's the key insight: in most realistic scenarios, there are multiple different functions that minimize error equally well.[1][2]

This happens because:

- **Data has noise**: Real-world data is messy. There are often multiple ways to fit noisy data equally well.
- **Models are over-parameterized**: Modern machine learning models, especially deep neural networks, have far more parameters (adjustable settings) than necessary to fit the training data. This flexibility means many different combinations of parameter values can achieve the same accuracy.
- **Arbitrary choices during training**: The order in which data is presented, random initialization of parameters, choice of hyperparameters (learning rate, batch size, etc.), and other factors that seem arbitrary all influence which specific model we end up with, even if multiple models would be equally accurate.[6]

### The Accuracy Problem

Here's a crucial insight: **accuracy alone is an incomplete basis for model selection**.[1] Two models can have identical accuracy on validation data but make completely different predictions on new patients. Standard validation metrics don't tell you which model to choose when multiple models are equally accurate.

This is a fundamental challenge in machine learning that becomes especially acute in high-stakes domains like medicine. We've been trained to think that if a model has 95% accuracy, we should use it. But what if there are ten different models with 95% accuracy that disagree on which 5% of cases are positive?

## The Problem: Arbitrary Predictions from Equally Valid Models

The recent research on predictive multiplicity in medical AI reveals the true extent of this problem. Let's break down what the study found:

### Finding 1: Standard Validation Metrics Fail to Identify a Uniquely Optimal Model

When researchers analyzed diverse medical tasks and model architectures, they discovered that standard validation metrics—the numbers we typically use to evaluate model performance—fail to identify a single best model. Instead, they identify a set of equally-valid models.[1][2]

This is like having five equally qualified candidates for a job and no objective way to choose between them. In hiring, you might flip a coin or let personal preference decide. In medicine, letting arbitrary factors decide which model to use is unacceptable.

### Finding 2: A Substantial Amount of Predictions Hinges on Arbitrary Choices

The research reveals that many patient predictions depend on choices made during model development that have nothing to do with the patient's actual medical data.[1] These arbitrary choices include:

- **Random seed selection**: The initial random values used to start training
- **Hyperparameter choices**: Learning rate, batch size, regularization strength, and dozens of other settings
- **Training order**: The order in which training data is presented
- **Model architecture decisions**: Which layers to include, how many neurons, etc.
- **Data preprocessing choices**: How to handle missing values, how to normalize features

None of these choices are based on medical science or patient data. Yet they influence which model you end up with, and if you have multiple equally-valid models, they influence which diagnosis a patient receives.

### Finding 3: Multiple Models Reveal Arbitrary Diagnoses

When researchers used multiple models instead of a single model, they discovered instances where predictions differed across equally-plausible models. These are the "multiplicity patients"—individuals who would receive different diagnoses depending on which equally-valid model was used.[1]

Imagine a patient with borderline symptoms. Model A, trained with a slightly different random seed, predicts disease present. Model B, equally accurate, predicts disease absent. The patient's actual condition hasn't changed, but their diagnosis has. This is the essence of predictive multiplicity in practice.

## Key Findings from Recent Research

The recent comprehensive study on predictive multiplicity in medical AI provides empirical evidence of how widespread and serious this problem is. Here are the major findings:

### Multiplicity is Widespread Across Medical Tasks

The research wasn't limited to one medical domain or one type of model. Across diverse medical tasks and model architectures, predictive multiplicity was observed. This suggests the problem is systemic, not limited to specific applications.[1]

### Small Ensembles Can Mitigate Multiplicity

One of the most encouraging findings is that using multiple models together—an ensemble—can effectively mitigate or even eliminate predictive multiplicity in practice.[1] Rather than using a single model and hoping it's the right one, using several equally-valid models together can provide more reliable predictions.

When multiple models agree on a diagnosis, that consensus is meaningful. It suggests the prediction isn't based on arbitrary choices but on genuine patterns in the data. Conversely, when models disagree, that disagreement is informative—it tells us the prediction is uncertain and potentially unreliable.

### Higher Accuracy Reduces Multiplicity

Interestingly, the research found that higher accuracy achieved through increased model capacity reduces predictive multiplicity.[1] Models that are more accurate tend to show less disagreement among equally-valid variants. This suggests that investing in better models—more sophisticated architectures, more training data, better features—can help address the multiplicity problem.

However, this isn't a complete solution. Accuracy alone won't eliminate multiplicity, but it helps.

### Abstention Strategies are Effective

The research recommends an **abstention strategy**: when models fail to reach sufficient consensus, defer decisions to expert review.[1] Rather than forcing a prediction when models disagree, the system can flag the case as uncertain and send it to a human expert.

This is a pragmatic approach that acknowledges the limitations of current AI while still leveraging its strengths. The AI handles the clear-cut cases where multiple models agree, and humans handle the uncertain cases where models disagree.

## Real-World Implications

Understanding predictive multiplicity has profound implications for how we deploy AI in healthcare:

### Diagnostic Reliability

The most immediate implication is for diagnostic reliability. If a patient's diagnosis depends partly on arbitrary choices made during model development, the diagnosis isn't as reliable as we thought. This is especially concerning for rare diseases where training data is limited and multiplicity is likely to be severe.

### Regulatory and Legal Issues

As healthcare AI systems face increasing regulatory scrutiny, the question of model selection becomes legally relevant. If a model makes an incorrect diagnosis and a lawsuit follows, how do you defend the choice of that model when multiple equally-valid alternatives existed? Predictive multiplicity creates liability.

### Patient Trust and Informed Consent

Patients deserve to know that their diagnosis might be partly arbitrary. If we're using AI to make medical decisions, patients should understand the limitations and uncertainties. Predictive multiplicity is one of those important limitations.

### Clinical Implementation

Healthcare institutions implementing AI systems need to be aware of multiplicity. They can't simply train one model and deploy it. They need to either:

- Use ensemble methods (multiple models)
- Implement abstention strategies (flag uncertain cases)
- Invest in higher-capacity models to reduce multiplicity
- Combine AI predictions with human expert review

## Solutions: Ensemble Methods and Beyond

The research on predictive multiplicity isn't just a problem statement—it also points toward solutions. Let's explore the most promising approaches:

### Ensemble Methods: Strength in Numbers

An ensemble combines multiple models, typically by averaging their predictions or using voting. The key insight is that multiple equally-valid models can work together to provide more reliable predictions than any single model.[1]

**How ensembles mitigate multiplicity:**

When multiple models agree, their consensus is meaningful. If 10 equally-valid models all predict disease present, that's strong evidence for the diagnosis. If they split 5-5, that's a clear signal that the prediction is uncertain.

Ensembles also reduce the impact of arbitrary choices. Even if each individual model is influenced by random initialization and hyperparameter choices, the ensemble average tends to be more stable. It's like asking 10 experts instead of 1—if they all agree, you can be more confident.

**Practical implementation:**

In practice, you don't need a huge ensemble. The research found that even small ensembles—perhaps 5-10 models—can effectively mitigate predictive multiplicity.[1] This is important because larger ensembles require more computational resources and are slower to run.

### Abstention Strategies: Know When to Defer

Rather than forcing a prediction when models disagree, an abstention strategy defers uncertain cases to human experts.[1] This requires defining a threshold for consensus: predictions with high inter-model agreement proceed automatically, while predictions with low agreement go to a human.

**Benefits of abstention:**

- Prevents arbitrary diagnoses in uncertain cases
- Provides human experts with information about which cases the AI finds difficult
- Maintains patient safety by ensuring difficult cases get human review
- Builds trust by being transparent about AI limitations

**Implementation considerations:**

Defining the right threshold is crucial. Too high, and you're deferring too many cases, making the AI less useful. Too low, and you're not adequately protecting against arbitrary predictions. The threshold should be set based on clinical requirements and resource availability.

### Improving Model Capacity: Better Models, Less Multiplicity

The research found that higher accuracy reduces predictive multiplicity.[1] This suggests that investing in better models—more sophisticated architectures, more training data, better feature engineering—can help address the problem.

**Approaches to improve model capacity:**

- **Larger datasets**: More training data provides clearer patterns and reduces the space of equally-valid models
- **Better features**: Domain expertise in feature engineering can improve model performance and reduce multiplicity
- **Advanced architectures**: Newer deep learning architectures often achieve better accuracy
- **Transfer learning**: Using knowledge from related tasks can improve performance on limited medical datasets

However, it's important to note that this isn't a complete solution. Multiplicity can still exist even in highly accurate models. The combination of improved accuracy plus ensemble methods and abstention strategies is more powerful than any single approach.

### Transparency and Reporting

Beyond technical solutions, the research advocates for better reporting of predictive multiplicity.[1] Healthcare institutions should:

- Report not just accuracy, but also measures of predictive multiplicity
- Disclose which cases show high inter-model disagreement
- Explain the arbitrary choices made during model development
- Provide confidence intervals or uncertainty estimates

This transparency helps clinicians understand the limitations of AI predictions and make better decisions about when to rely on AI and when to seek additional expert review.

## Key Concepts to Remember

As you think about predictive multiplicity and its implications, here are seven key concepts that are useful across computer science and AI topics:

### 1. Model Multiplicity
The existence of multiple machine learning models that describe data equally well but may differ in their internals or predictions. This is a fundamental property of machine learning that becomes especially important in high-stakes domains.[1]

### 2. Predictive Multiplicity
A specific type of model multiplicity where competing models make conflicting predictions on individual samples despite having equal accuracy.[2] This is the problem that matters most for applications like medical diagnosis.

### 3. Accuracy is Incomplete
Accuracy metrics alone don't tell you which model to use when multiple models are equally accurate. This challenges conventional wisdom in machine learning and suggests we need additional criteria for model selection.[1]

### 4. Arbitrary Choices Matter
Seemingly arbitrary decisions during model training—random seeds, hyperparameters, training order—can influence which model you end up with and thus which predictions it makes. In high-stakes applications, this arbitrariness is problematic.

### 5. Ensemble Robustness
Using multiple models together can mitigate predictive multiplicity and provide more reliable predictions. The consensus of multiple models is more meaningful than the prediction of a single model.[1]

### 6. Uncertainty Quantification
Rather than always producing a single prediction, AI systems should quantify their uncertainty. High disagreement among multiple models indicates low confidence; high agreement indicates high confidence.

### 7. Human-AI Collaboration
Rather than replacing human experts, AI systems should work alongside them. Abstention strategies that defer uncertain cases to humans create a more robust system than either AI or humans alone.[1]

## The Future of Reliable Medical AI

Understanding predictive multiplicity is crucial for building AI systems that clinicians and patients can trust. The research on this topic points toward a future where medical AI is more transparent, more reliable, and more integrated with human expertise.

### Moving Away from Single-Model Deployment

The era of deploying a single trained model and treating it as the definitive solution is ending. As awareness of model multiplicity grows, best practices will shift toward:

- **Ensemble-based systems**: Multiple models working together
- **Uncertainty quantification**: Clear reporting of when the AI is confident vs. uncertain
- **Human integration**: AI handling routine cases, humans handling uncertain ones
- **Continuous monitoring**: Tracking whether the AI's predictions align with actual outcomes

### Regulatory Evolution

As regulatory bodies like the FDA become more sophisticated in their understanding of AI, they will likely require manufacturers to:

- Report measures of predictive multiplicity
- Demonstrate that their models are robust to arbitrary choices in training
- Show how they've addressed the problem of conflicting predictions
- Provide mechanisms for abstention or uncertainty reporting

### Clinical Practice Changes

Clinicians will increasingly understand that AI predictions come with uncertainty and that disagreement between models is informative. Rather than treating AI as a black box that produces definitive answers, they'll view it as a tool that provides evidence to be considered alongside other clinical information.

### Research Directions

The study of predictive multiplicity is still relatively new. Future research will likely explore:

- **Causal multiplicity**: Understanding which features of the data drive multiplicity
- **Domain-specific solutions**: Developing approaches tailored to specific medical domains
- **Theoretical foundations**: Deeper understanding of why multiplicity occurs and how to prevent it
- **Practical implementation**: How to deploy ensemble-based systems efficiently in clinical settings

## Conclusion

Predictive multiplicity represents a fundamental challenge in machine learning that becomes acute in high-stakes domains like medicine. The recent research on this topic reveals that many medical AI systems can produce conflicting predictions from equally-valid models, meaning some patient diagnoses are partly determined by arbitrary choices made during model development rather than by the patient's actual medical data.

This isn't a reason to abandon medical AI. Rather, it's a call to build better, more thoughtful AI systems. By understanding predictive multiplicity and implementing solutions like ensemble methods, abstention strategies, and improved model capacity, we can create AI systems that are more reliable, more transparent, and more trustworthy.

The path forward requires collaboration between machine learning researchers, healthcare professionals, and policymakers. It requires acknowledging that accuracy alone isn't enough, and that in medicine, reliability and defensibility matter as much as raw predictive power. As medical AI continues to advance, understanding and addressing predictive multiplicity will be essential to ensuring that AI serves patients well.

## Resources

- [On Arbitrary Predictions from Equally Valid Models](https://arxiv.org/abs/2507.19408) - The original research paper analyzing predictive multiplicity in medical AI
- [Model Multiplicity: Opportunities, Concerns, and Solutions](https://dl.acm.org/doi/10.1145/3531146.3533149) - Comprehensive overview of model multiplicity phenomenon and implications
- [Predictive Multiplicity in Classification](https://proceedings.mlr.press/v119/marx20a.html) - Foundational work defining predictive multiplicity with mathematical frameworks
- [Disentangling Model Multiplicity in Deep Learning](https://arxiv.org/pdf/2206.08890) - Analysis of representational multiplicity in deep neural networks
- [The Dataset Multiplicity Problem](https://pages.cs.wisc.edu/~aws/papers/facct23.pdf) - Related work on how data choices affect model multiplicity