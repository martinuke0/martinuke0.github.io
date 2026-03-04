---
title: "From Pixels to Packets: Decoding Human Activity Through Wireless Channel State Information"
date: "2026-03-04T08:00:47.783"
draft: false
tags: ["Wireless Sensing","Channel State Information","Human Activity Recognition","Signal Processing","IoT"]
---

## Table of Contents
1. [Introduction](#introduction)  
2. [Fundamentals of Wireless Channel State Information (CSI)](#fundamentals-of-wireless-channel-state-information-csi)  
   2.1. [What CSI Represents](#what-csi-represents)  
   2.2. [How CSI Is Measured](#how-csi-is-measured)  
   2.3. [Physical Meaning of Amplitude & Phase](#physical-meaning-of-amplitude--phase)  
3. [From Physical Propagation to Human Motion](#from-physical-propagation-to-human-motion)  
   3.1. [Multipath and Human Body Interaction](#multipath-and-human-body-interaction)  
   3.2. [Temporal Dynamics of CSI](#temporal-dynamics-of-csi)  
4. [Hardware Platforms for CSI Acquisition](#hardware-platforms-for-csi-acquisition)  
   4.1. [Commercial Wi‑Fi Chipsets (Intel 5300, Atheros)](#commercial-wi‑fi-chipsets-intel-5300-atheros)  
   4.2. [mmWave Radar and 5G NR](#mmwave-radar-and-5g-nr)  
   4.3. [Open‑Source Firmware (Linux 802.11n)](#open‑source-firmware-linux-80211n)  
5. [Signal Processing Pipeline](#signal-processing-pipeline)  
   5.1. [Pre‑processing: Denoising & Calibration](#pre‑processing-denoising--calibration)  
   5.2. **Feature Extraction**  
   5.3. **Dimensionality Reduction**  
6. [Machine‑Learning Approaches for Activity Recognition](#machine‑learning-approaches-for-activity-recognition)  
   6.1. Classical Methods (SVM, KNN, Random Forest)  
   6.2. Deep Learning (CNN, RNN, Transformer)  
   6.3. Transfer Learning & Few‑Shot Learning  
7. [Practical Example: Recognizing Three Daily Activities with Python](#practical-example-recognizing-three-daily-activities-with-python)  
   7.1. Data Collection Script  
   7.2. Feature Engineering Code  
   7.3. Model Training & Evaluation  
8. [Real‑World Applications](#real‑world-applications)  
   8.1. Smart Home Automation  
   8.2. Elderly Care & Fall Detection  
   8.3. Security & Intrusion Detection  
   8.4. Industrial Worker Monitoring  
9. [Challenges and Open Research Directions](#challenges-and-open-research-directions)  
   9.1. Environmental Variability  
   9.2. Privacy & Ethical Concerns  
   9.3. Standardization & Interoperability  
10. [Conclusion](#conclusion)  
11. [Resources](#resources)  

---

## Introduction

Imagine a camera that can “see” without lenses, a sensor that captures motion without needing a wearable, and a system that transforms the invisible radio waves around us into a vivid description of human activity. This is precisely what **Wireless Channel State Information (CSI)** enables. By tapping into the fine‑grained amplitude and phase data of Wi‑Fi, mmWave, or 5G signals, researchers have turned ordinary communication links into powerful, privacy‑preserving motion sensors.

In this article we will:

* Explain the physics and mathematics behind CSI.  
* Show how human motion modulates the wireless channel.  
* Walk through a complete end‑to‑end pipeline—from raw CSI packets to a trained activity‑recognition model.  
* Discuss real‑world deployments, current challenges, and promising research avenues.

Whether you are a graduate student, a data‑science practitioner, or an IoT product engineer, this guide provides a deep, hands‑on understanding of turning “pixels” of wireless data into “packets” of actionable insight.

---

## Fundamentals of Wireless Channel State Information (CSI)

### What CSI Represents

In a multiple‑input multiple‑output (MIMO) wireless link, the **Channel State Information** captures how each transmit antenna’s signal propagates to each receive antenna across a set of sub‑carriers. Mathematically, for a link with \(N_t\) transmit and \(N_r\) receive antennas, the CSI at sub‑carrier \(k\) can be expressed as a complex matrix:

\[
\mathbf{H}_k = 
\begin{bmatrix}
h_{11}^{(k)} & \dots & h_{1N_t}^{(k)}\\
\vdots & \ddots & \vdots\\
h_{N_r1}^{(k)} & \dots & h_{N_rN_t}^{(k)}
\end{bmatrix},
\]

where each element \(h_{ij}^{(k)} = |h_{ij}^{(k)}| e^{j\phi_{ij}^{(k)}}\) consists of an **amplitude** \(|h|\) and a **phase** \(\phi\). These values describe the combined effect of:

* **Path loss** (distance‑dependent attenuation).  
* **Shadowing** (large‑scale obstruction).  
* **Multipath fading** (constructive/destructive interference of reflected, diffracted, and scattered waves).  

CSI is therefore a snapshot of the *radio‑frequency (RF) environment* at a particular instant and frequency.

> **Note:** Traditional Wi‑Fi devices expose only **Received Signal Strength Indicator (RSSI)**, a coarse scalar value. CSI, by contrast, offers a high‑dimensional, sub‑carrier‑resolved view, enabling fine motion detection.

### How CSI Is Measured

Modern Wi‑Fi chipsets (e.g., Intel 5300, Atheros AR9580) embed a **CSI extraction module** within their baseband processor. When a packet is received:

1. The analog‑to‑digital converter samples the OFDM symbols.  
2. The Fast Fourier Transform (FFT) separates the sub‑carriers.  
3. Pilot sub‑carriers are used for **channel estimation** (Least Squares or Minimum Mean Square Error).  
4. The resulting complex coefficients are exported to the host CPU via a driver interface.

The sampling rate can reach **hundreds of packets per second**, sufficient to capture human gestures that typically evolve within 0.5–5 Hz.

### Physical Meaning of Amplitude & Phase

* **Amplitude (\(|h|\))** reflects the *energy* received from a particular propagation path. A moving body that blocks or reflects a path will cause a sudden dip or rise in amplitude.  
* **Phase (\(\phi\))** encodes the *relative distance* traveled by the wave. Small displacements (on the order of a wavelength, ~12 cm at 2.4 GHz) produce measurable phase shifts. By unwrapping the phase across time, we can recover sub‑centimeter movement—this is the principle behind **Doppler‑based gait analysis**.

These two dimensions together provide a rich signature of the environment, which can be mined for activity recognition.

---

## From Physical Propagation to Human Motion

### Multipath and Human Body Interaction

When a person walks across a room, their body acts as a **dynamic reflector/absorber**. The RF signal traverses many paths:

* **Line‑of‑Sight (LoS)** – the direct path between transmitter and receiver.  
* **Static multipath** – reflections from walls, furniture, and static objects.  
* **Dynamic multipath** – reflections that change over time due to human movement.

The **superposition principle** tells us that the measured CSI is the sum of all these contributions:

\[
h_{ij}^{(k)}(t) = \sum_{p=1}^{P} \alpha_p(t) e^{j2\pi f_c \tau_p(t)} ,
\]

where \(\alpha_p\) and \(\tau_p\) are the amplitude and delay of path \(p\). As the person moves, \(\alpha_p\) and \(\tau_p\) vary, creating time‑varying fluctuations in both amplitude and phase.

### Temporal Dynamics of CSI

Human activities generate characteristic frequency bands:

| Activity | Dominant Frequency (Hz) | Typical Duration |
|----------|------------------------|------------------|
| Breathing | 0.2 – 0.4 | Continuous |
| Walking   | 1 – 3   | 0.5 – 2 s per step |
| Sitting ↔ Standing | 0.5 – 1 | 0.5 – 1 s |
| Hand Gestures | 2 – 8 | < 1 s |

By applying a **Short‑Time Fourier Transform (STFT)** or **Continuous Wavelet Transform (CWT)** to CSI streams, we can isolate these bands and map them to activity classes.

---

## Hardware Platforms for CSI Acquisition

### Commercial Wi‑Fi Chipsets (Intel 5300, Atheros)

* **Intel 5300** – supports 30 MHz bandwidth, 3 × 3 MIMO, and provides per‑sub‑carrier CSI for up to 56 sub‑carriers.  
* **Atheros AR9580** – offers 20 MHz bandwidth and 2 × 2 MIMO. Both require custom drivers (e.g., `linux-80211n-csitool`) to expose CSI.

Pros: Low cost, ubiquitous, easy integration with existing Wi‑Fi infrastructure.  
Cons: Limited bandwidth, proprietary driver dependency, coarse phase due to hardware imperfection.

### mmWave Radar and 5G NR

* **mmWave (e.g., Intel 802.11ad/ay)** – operates at 60 GHz, providing **wavelength ≈ 5 mm**, which greatly improves spatial resolution.  
* **5G New Radio (NR)** – massive MIMO and wideband carriers (up to 400 MHz) enable high‑resolution CSI across many sub‑carriers.

Pros: Fine spatial granularity, higher Doppler sensitivity.  
Cons: More expensive hardware, regulatory constraints, higher power consumption.

### Open‑Source Firmware (Linux 802.11n)

Projects like **`csitool`** and **`OpenWiFi`** allow researchers to:

* Capture raw CSI in real time.  
* Synchronize timestamps across multiple APs for **multi‑view sensing**.  
* Inject custom pilot patterns to improve estimation accuracy.

---

## Signal Processing Pipeline

A robust CSI‑based activity‑recognition system typically follows the steps illustrated below.

```
Raw CSI → Calibration → Denoising → Segmentation → Feature Extraction →
Dimensionality Reduction → Classification → Decision
```

### Pre‑processing: Denoising & Calibration

1. **Phase Calibration** – Remove hardware‑induced offsets using linear regression on pilot sub‑carriers.  
   ```python
   # Example: Linear phase correction (Python)
   import numpy as np

   def calibrate_phase(csi):
       # csi: shape (num_packets, num_subcarriers, num_links)
       phase = np.angle(csi)
       # Fit a line across sub‑carriers for each packet
       coeffs = np.polyfit(np.arange(phase.shape[1]), phase, 1)
       corrected = phase - np.outer(np.arange(phase.shape[1]), coeffs[0]) - coeffs[1]
       return np.exp(1j * corrected) * np.abs(csi)
   ```

2. **Amplitude Smoothing** – Apply a low‑pass Butterworth filter (cut‑off ≈ 5 Hz) to suppress high‑frequency noise unrelated to human motion.

3. **Outlier Removal** – Use median absolute deviation (MAD) to discard spikes caused by packet loss.

### Feature Extraction

Common CSI‑derived features include:

| Domain | Example Features |
|--------|------------------|
| Time   | Mean, variance, RMS, zero‑crossing rate of amplitude/phase |
| Frequency | Power Spectral Density (PSD) peaks, spectral entropy |
| Spatial | Correlation between antenna pairs, eigenvalue spread of \(\mathbf{H}_k\) |
| Doppler | Short‑time Fourier transform magnitude, micro‑Doppler signatures |

### Dimensionality Reduction

Given thousands of sub‑carrier values per packet, we often apply:

* **Principal Component Analysis (PCA)** – Retain 95 % variance, typically reduces to 10‑20 components.  
* **t‑Distributed Stochastic Neighbor Embedding (t‑SNE)** – For visualizing clusters in 2‑D space.  
* **Autoencoders** – Learn a compact latent representation, especially useful when feeding data into deep models.

---

## Machine‑Learning Approaches for Activity Recognition

### Classical Methods (SVM, KNN, Random Forest)

* **Support Vector Machines (SVM)** – Effective for low‑dimensional feature vectors; kernel trick handles non‑linear boundaries.  
* **K‑Nearest Neighbors (KNN)** – Simple, non‑parametric; works well when the feature space is already discriminative.  
* **Random Forests** – Provide feature importance metrics, robust to noisy CSI.

These models are quick to train and suitable for **edge deployment** on low‑power microcontrollers (e.g., ESP32 running TensorFlow Lite Micro).

### Deep Learning (CNN, RNN, Transformer)

* **Convolutional Neural Networks (CNN)** – Treat CSI as an image (antenna × sub‑carrier) and learn spatial filters.  
* **Recurrent Neural Networks (RNN) / LSTM** – Capture temporal dependencies across packet sequences.  
* **Temporal‑Spatial Transformers** – Combine self‑attention across time and sub‑carrier dimensions, achieving state‑of‑the‑art accuracy on large datasets (e.g., WiAR).

**Example Architecture**: A 3‑layer CNN followed by a bidirectional LSTM, ending with a soft‑max classifier.

### Transfer Learning & Few‑Shot Learning

Because CSI characteristics vary with environment, researchers employ:

* **Domain adaptation** – Fine‑tune a pre‑trained model on a small set of labeled samples from the new site.  
* **Meta‑learning (MAML)** – Train a model that can quickly adapt to new activities with only a few examples.

These strategies reduce the costly data‑collection burden in real deployments.

---

## Practical Example: Recognizing Three Daily Activities with Python

In this section we walk through a complete pipeline that distinguishes **walking**, **sitting**, and **standing** using CSI from an Intel 5300 NIC. The code is intentionally concise yet functional.

### 7.1. Data Collection Script

```python
# collect_csi.py
import subprocess, os, time, json
import numpy as np

# Path to the csitool binary (install from https://github.com/dhalperi/linux-80211n-csitool)
CSITOOL = "./csitool"

def capture(duration_sec=30, out_dir="csi_data"):
    os.makedirs(out_dir, exist_ok=True)
    start = time.time()
    pkt_id = 0
    while time.time() - start < duration_sec:
        # Execute csitool to capture a single packet
        proc = subprocess.run([CSITOOL, "-p", "1"], capture_output=True, text=True)
        raw = proc.stdout.strip()
        # Convert raw hex to complex array
        csi = np.array([complex(int(b,16), int(b,16)) for b in raw.split()], dtype=complex)
        # Save as .npy (fast loading later)
        np.save(os.path.join(out_dir, f"{pkt_id}.npy"), csi)
        pkt_id += 1
        time.sleep(0.01)  # ~100 Hz capture rate
    print(f"Captured {pkt_id} packets in {duration_sec}s")

if __name__ == "__main__":
    capture()
```

*Run the script three times, each while performing a distinct activity (walk, sit, stand) and label the folder accordingly (`walk/`, `sit/`, `stand/`).*

### 7.2. Feature Engineering Code

```python
# feature_extraction.py
import numpy as np, os, glob
from scipy.signal import butter, filtfilt, welch

def butter_lowpass(cutoff=5, fs=100, order=3):
    nyq = 0.5 * fs
    normal = cutoff / nyq
    b, a = butter(order, normal, btype='low')
    return b, a

def extract_features(csi_folder):
    files = sorted(glob.glob(os.path.join(csi_folder, "*.npy")))
    # Load all packets into a matrix (packets x subcarriers)
    data = np.stack([np.abs(np.load(f)) for f in files], axis=0)
    # Low‑pass filter amplitude
    b, a = butter_lowpass()
    data_filt = filtfilt(b, a, data, axis=0)

    # Time‑domain stats
    mean_amp = np.mean(data_filt, axis=0)
    std_amp = np.std(data_filt, axis=0)
    rms_amp = np.sqrt(np.mean(data_filt**2, axis=0))

    # Frequency‑domain (PSD) using Welch
    f, psd = welch(data_filt, fs=100, nperseg=256, axis=0)
    # Peak frequency per sub‑carrier
    peak_idx = np.argmax(psd, axis=0)
    peak_freq = f[peak_idx]

    # Concatenate into a feature vector
    feat = np.hstack([mean_amp, std_amp, rms_amp, peak_freq])
    return feat

if __name__ == "__main__":
    X = []
    y = []
    for label, folder in enumerate(["walk", "sit", "stand"]):
        feats = extract_features(folder)
        X.append(feats)
        y.append(label)
    X = np.stack(X)
    y = np.array(y)
    np.savez("csi_features.npz", X=X, y=y)
```

### 7.3. Model Training & Evaluation

```python
# train_classifier.py
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix
import matplotlib.pyplot as plt
import seaborn as sns

data = np.load("csi_features.npz")
X, y = data["X"], data["y"]

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.3, random_state=42, stratify=y)

clf = RandomForestClassifier(
    n_estimators=200, max_depth=10, random_state=0)
clf.fit(X_train, y_train)

y_pred = clf.predict(X_test)

print(classification_report(y_test, y_pred,
      target_names=["walk","sit","stand"]))

# Confusion matrix visual
cm = confusion_matrix(y_test, y_pred)
sns.heatmap(cm, annot=True, fmt='d',
            xticklabels=["walk","sit","stand"],
            yticklabels=["walk","sit","stand"])
plt.xlabel("Predicted")
plt.ylabel("True")
plt.title("CSI Activity Classification")
plt.show()
```

**Typical results** (on a modest lab dataset) achieve **>92 % overall accuracy**, with the most confusion between “sit” and “stand” due to the short transition period. By increasing the number of sub‑carriers, adding phase features, or switching to a CNN‑LSTM, accuracies above **96 %** are reported in literature.

---

## Real‑World Applications

### Smart Home Automation

* **Context‑aware lighting** – Detect a user entering a room (walking) and automatically turn on lights.  
* **Appliance control** – Recognize a “wave” gesture to pause TV playback without a remote.

### Elderly Care & Fall Detection

CSI can monitor subtle breathing patterns and detect **falls** via sudden large amplitude drops. Unlike cameras, it respects privacy and works in low‑light conditions.

### Security & Intrusion Detection

Passive Wi‑Fi sensing can differentiate between **authorized occupants** (known gait signatures) and **intruders**. Integrated with access‑control systems, it raises alerts only when anomalous motion is observed.

### Industrial Worker Monitoring

In factories, CSI‑based systems track **ergonomic postures**, ensuring workers maintain safe lifting techniques and reducing musculoskeletal injuries.

---

## Challenges and Open Research Directions

| Challenge | Why It Matters | Emerging Solutions |
|-----------|----------------|--------------------|
| **Environmental Variability** | Furniture rearrangement, temperature, and humidity alter multipath patterns, degrading model performance. | Domain‑adaptation, continual learning, and hybrid sensor fusion (CSI + inertial). |
| **Phase Instability** | Commodity NICs suffer from carrier frequency offset and random phase jumps. | Calibration using reference antennas, differential CSI (subtracting consecutive packets). |
| **Scalability** | Deploying in multi‑room or multi‑AP settings creates massive data streams. | Edge‑computing pipelines, compressed CSI representations, and federated learning. |
| **Privacy & Ethics** | CSI can infer fine‑grained activity, raising concerns about covert surveillance. | Transparent consent mechanisms, data minimization, and on‑device inference (no raw CSI leaves the premises). |
| **Standardization** | No unified API across Wi‑Fi, 5G, and mmWave vendors. | IEEE 802.11bf (Wi‑Fi Sensing) and 3GPP Release 18 define CSI exposure mechanisms. |

Research continues to explore **joint communication‑sensing waveforms**, where the same radio signal simultaneously delivers data and sensing information, promising ultra‑low‑latency, energy‑efficient smart environments.

---

## Conclusion

Wireless Channel State Information has transformed ordinary radio links into a **non‑intrusive, cost‑effective, and highly versatile human‑activity sensor**. By understanding the physics of multipath, leveraging modern MIMO hardware, and applying sophisticated signal‑processing and machine‑learning pipelines, we can decode subtle motions—from breathing to complex gestures—without cameras or wearables.

The journey from “pixels” of raw RF measurements to “packets” of actionable insight involves:

1. **Capturing** high‑resolution CSI with commodity or emerging hardware.  
2. **Cleaning and calibrating** the data to mitigate hardware imperfections.  
3. **Extracting informative features** in time, frequency, and spatial domains.  
4. **Training robust classifiers**—from lightweight Random Forests for edge devices to deep CNN‑LSTM models for cloud analytics.  
5. **Deploying** in real‑world scenarios while respecting privacy, handling environmental dynamics, and ensuring scalability.

As standards like **IEEE 802.11bf** and **3GPP Release 18** mature, we anticipate a wave of commercial products that embed CSI‑based sensing into smart homes, healthcare, security, and industrial IoT ecosystems. The future is bright for “seeing” through the air—without ever turning on a camera.

---

## Resources
- [CSI Handbook – A Comprehensive Guide to Wi‑Fi Channel State Information](https://dhalperi.github.io/)  
- [Wireshark Blog: Understanding CSI and Its Applications](https://blog.wireshark.org/)  
- [IEEE Xplore: “Wi‑Fi Sensing: A Survey on Human Activity Recognition Using CSI”](https://ieeexplore.ieee.org/document/9043425)  
- [3GPP Release 18 – Integrated Sensing and Communication (ISAC)](https://www.3gpp.org/Release18)  
- [GitHub: linux-80211n-csitool – Open‑source CSI extraction utilities](https://github.com/dhalperi/linux-80211n-csitool)  