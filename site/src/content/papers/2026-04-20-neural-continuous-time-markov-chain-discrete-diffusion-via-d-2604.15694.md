---
title: "Neural Continuous-Time Markov Chain: Discrete Diffusion via Decoupled Jump Timing and Direction"
arxivId: "2604.15694"
publishedDate: 2026-04-20
paperDate: 2026-04-17
primaryCategory: cs.LG
pdfUrl: https://arxiv.org/pdf/2604.15694v1
absUrl: https://arxiv.org/abs/2604.15694
pickReason: Directly advances transformer efficiency through novel CTMC-based discrete diffusion parameterization with fundamental algorithmic contribution, aligns with high-priority attention variants and sparse modeling interests.
tldr: Neural CTMC decomposes discrete diffusion into exit rates (when) and jump distributions (where), achieving first uniform-noise win over masked methods on OpenWebText
hook: What if discrete diffusion models have been parameterizing the wrong thing all along? This paper shows the training objective naturally factorizes into timing and direction.
authors:
  - Jingyuan Li
  - Xiaoyi Jiang
  - Fukang Wen
  - Wei Liu
  - Renqian Luo
  - Yi Zhu
  - Zuoqiang Shi
  - Pipi Hu
tags:
  - generative-models
  - cs-LG
  - language-models
  - markov-chains
  - transformers
  - discrete-diffusion
  - ctmc
---

## TL;DR

Discrete diffusion models for text generation have parameterized the reverse process as a monolithic rate matrix, but CTMCs naturally decompose into exit rates (when to jump) and jump distributions (where to jump). Neural CTMC separately parameterizes these two components with dedicated network heads, achieving a decomposed training objective that factorizes into Poisson KL for timing and categorical KL for direction. This decomposition enables the first pure-uniform-noise discrete diffusion model to outperform mask-based methods on OpenWebText.

## Why this matters

Current discrete diffusion models treat the reverse rate matrix as a single object, learning it through proxy quantities like score ratios or clean-data predictions. This monolithic approach misses a fundamental structural property: any CTMC rate matrix uniquely factorizes into an exit rate (controlling holding times) and a jump distribution (controlling destinations). This decomposition is the basis of Gillespie's algorithm for CTMC simulation, yet no prior discrete diffusion method has reflected it in the parameterization.

The uniform forward process, which allows transitions among all vocabulary tokens throughout generation, has consistently underperformed the simpler masked (absorbing) process that corrupts tokens to a special mask state. Once masked, tokens cannot be revisited, preventing error correction during generation. Despite this limitation, masked methods dominate current benchmarks because uniform-noise methods have struggled with optimization and sample quality.

Neural CTMC addresses both issues. The decomposed parameterization aligns with the intrinsic CTMC structure, providing separate learning signals for timing and direction decisions. This enables strong performance with a pure uniform forward processâon OpenWebText, it achieves the best results among equal-budget methods across multiple sampling step counts, marking the first time a pure-uniform method has beaten mask-based approaches on this benchmark.

## Background

Understanding Neural CTMC requires familiarity with continuous-time Markov chains and their path measures. A CTMC on a finite state space is characterized by a rate matrix $R_t(i,j)$ giving instantaneous transition rates. The key insight is that any rate matrix admits a unique factorization: $R_t(i,j) = \lambda_t(i) \cdot r_t(j|i)$, where $\lambda_t(i)$ is the exit rate from state $i$ and $r_t(\cdot|i)$ is a categorical distribution over jump destinations.

Three prior works form the foundation: **Campbell et al. (2022)** established the continuous-time framework for discrete diffusion, deriving the ELBO from CTMC path measures. **MDLM (Sahoo et al., 2024)** simplified training for masked diffusion via clean-data prediction, achieving strong language modeling results. **SEDD (Lou et al., 2024)** introduced concrete score matching for discrete diffusion, learning score ratios $q_t(j)/q_t(i)$ analogous to continuous diffusion.

## The core idea

Think of text generation as a restaurant kitchen during dinner rush. Current methods give chefs a single instruction: "make dish X in Y minutes." Neural CTMC instead separates this into two decisions: "when should you start the next dish?" (exit rate) and "which dish should you make?" (jump distribution). Just as separating timing from menu selection helps kitchen flow, decomposing the CTMC dynamics helps the model learn more efficiently.

The mathematical insight is that the training objective itself naturally decomposes along this structure. The reverse-process KL divergenceâwhich measures how well the learned process matches the true reverseâsplits into a Poisson KL for exit rates and a categorical KL weighted by the exit rate for jump distributions. This isn't an architectural choice imposed externally; it emerges from the path-space objective, suggesting that timing and direction should be learned with separate heads.

## The method

### Problem Setup

Given a finite vocabulary $\mathcal{S} = \{1, ..., S\}$, the forward process corrupts data $X_0 \sim p_{\text{data}}$ via a CTMC with rate matrix $R_t$. For the uniform forward process:

$$R_t(i,j) = \beta_t \quad \text{for } i \neq j$$

where $\beta_t = t/T$ increases linearly. The transition probabilities have closed form:

$$q_{t|0}(j|i) = \text{Cat}(j; P_t e_i), \quad P_t = \alpha_t I + \beta_t \pi \mathbf{1}^T$$

with $\alpha_t = 1-t/T$ and $\pi$ the target prior (uniform distribution $\mathbf{1}/S$ in experiments).

### Neural Parameterization

Instead of learning a proxy for $R_t^\theta(i,j)$, Neural CTMC directly parameterizes:

$$\Phi_\theta(x_t, t) = \left(\lambda_t^\theta(x_t), r_t^\theta(\cdot|x_t)\right)$$

where $\lambda_t^\theta(x_t) \in \mathbb{R}_{>0}$ is the exit rate and $r_t^\theta(\cdot|x_t) \in \Delta^{S-1}$ is the jump distribution. The reverse rate matrix is then:

$$R_t^\theta(i,j) = \lambda_t^\theta(i) \cdot r_t^\theta(j|i) \quad \text{for } j \neq i$$

### Training Objective

The key theoretical result shows the ELBO's $\theta$-dependent part equals a reverse-process KL up to a constant:

$$\mathbb{E}_{p_{\text{data}}}[-\log p_\theta(x_0)] \leq \text{KL}(\hat{Q} \| P^\theta) + C$$

where $\hat{Q}$ is the true reverse path measure and $P^\theta$ is the learned reverse. This KL decomposes:

$$\text{KL}(\hat{Q} \| P^\theta) = \int_0^T \sum_{i \in \mathcal{S}} q_t(i) \left[\text{KL}_{\text{Poi}}(\hat{\lambda}_t(i) \| \lambda_t^\theta(i)) + \hat{\lambda}_t(i) \cdot \text{KL}_{\text{Cat}}(\hat{r}_t(\cdot|i) \| r_t^\theta(\cdot|i))\right] dt$$

The Poisson KL is $\text{KL}_{\text{Poi}}(\lambda \| \lambda^\theta) = \lambda \log(\lambda/\lambda^\theta) - \lambda + \lambda^\theta$, and the categorical KL is the standard KL between discrete distributions.

### Practical Loss Function

Since marginal quantities $q_t(i)$ are intractable, the method uses conditional quantities. The tractable loss becomes:

$$\mathcal{L}(\theta) = \mathbb{E}_{t,x_0,i} \left[\sum_{j \neq i} \lambda_t^\theta(i)r_t^\theta(j|i) - \sum_{j \neq i} R_t(j,i)\frac{q_{t|0}(j|x_0)}{q_{t|0}(i|x_0)} \log \frac{\lambda_t^\theta(i)r_t^\theta(j|i)}{R_t(j,i)} + K\left(\frac{q_{t|0}(j|x_0)}{q_{t|0}(i|x_0)}\right)\right]$$

where $K(a) = a(\log a - 1)$ and the last term is $\theta$-independent. The expectation is over $t \sim U(0,T)$, $x_0 \sim p_{\text{data}}$, and $i \sim q_{t|0}(\cdot|x_0)$.

### Architecture

The model uses a 12-layer DiT (Diffusion Transformer) with:
- Hidden dimension: 768
- Attention heads: 12  
- Time conditioning: 128-dimensional embeddings
- Vocabulary embedding: 50304 (rounded up for hardware efficiency)
- Total parameters: ~163M

The transformer outputs are projected to two heads:
1. Exit rate head: single scalar per position, exponentiated for positivity
2. Jump distribution head: $(S-1)$-dimensional logits, softmaxed

### Sampling Algorithms

Two samplers leverage the decomposition:

**Ï-Leaping**: Samples number of jumps from Poisson($\lambda_t^\theta(x_t) \cdot \tau$), then sequentially samples destinations from $r_t^\theta(\cdot|x_t)$

**Euler**: Constructs one-step transition with $p_j = \lambda_t^\theta(x_t) \cdot r_t^\theta(j|x_t) \cdot \tau$ for $j \neq x_t$

Critical hyperparameters:
- Training: $t \sim U(\epsilon, T)$ with $\epsilon = 0.01$ to avoid near-$t=0$ high variance
- Sampling: 16-128 steps, step size $\tau = T/N$
- Uniform noise schedule: $\alpha_t = 1-t/T$, $\beta_t = t/T$

## Architecture

```mermaid
graph TD
    A[Input Text x_0] --> B[Sample t ~ U(0,T)]
    B --> C[Compute q_{t|0}]
    C --> D[Sample x_t ~ q_{t|0}(Â·|x_0)]
    D --> E[DiT Encoder]
    B --> E
    E --> F[Exit Rate Head]
    E --> G[Jump Distribution Head]
    F --> H[Î»_t^Î¸(x_t)]
    G --> I[r_t^Î¸(Â·|x_t)]
    H --> J[Poisson KL Loss]
    I --> K[Categorical KL Loss]
    J --> L[Total Loss]
    K --> L
    L --> M[Backprop]
```

## Results

On TinyStories with 50 sampling steps, Neural CTMC achieves generative perplexity â¤16.36 (Euler) and â¤16.38 (Ï-leaping) at epoch 50, compared to â¤37.60 for GIDD and â¤42.66 for MDLM under identical training conditions. The performance gap emerges after epoch 10 and widens consistently, suggesting the decomposed objective provides stronger gradients in later optimization stages.

On OpenWebText with 262B training tokens, Neural CTMC outperforms all equal-budget baselines across 16-128 sampling steps. At 32 steps, Ï-leaping achieves â¤258.8 perplexity versus â¤553.7 for MDLM (2.1Ã improvement) and â¤398.9 for GIDD with optimal interpolation (1.5Ã improvement). Against SEDD (which uses 682B tokens, 2.6Ã more), Neural CTMC is stronger at low step counts but weaker at 128 steps (â¤183.6 vs â¤127.2), likely reflecting the training budget difference.

The most convincing result is the consistent superiority over mask-based methods on OpenWebTextâthis marks the first time a pure uniform forward process has achieved this on a large-scale benchmark. The ablation between Euler and Ï-leaping samplers shows minimal performance difference, validating that both sampling strategies effectively exploit the exit-rate/jump-distribution decomposition.

## Limitations

The method requires computing and storing both exit rates and jump distributions, potentially doubling memory compared to methods that only predict clean tokens. The uniform forward process, while theoretically more flexible, requires longer sampling chains than masked diffusion for comparable qualityâmasked methods can often produce reasonable text in 8-16 steps while Neural CTMC needs 32+ steps.

The evaluation focuses on unconditional generation with perplexity metrics. The paper doesn't evaluate controllable generation, infilling tasks, or downstream applications where masked models might have advantages. The theoretical analysis assumes the conditional surrogate preserves gradients of the marginal objective, but this requires regularity conditions that may not hold exactly in practice.

The OpenWebText comparison isn't perfectly controlledâdifferent methods use different tokenizers and preprocessing pipelines in their original implementations, though the authors attempt to standardize evaluation. The method hasn't been tested on other discrete domains like proteins or molecules where the uniform noise assumption might be less appropriate.

## Reimplementation notes

The core implementation challenge is numerical stability in the loss computation. Near $t \approx T$, the conditional rates $\hat{\lambda}_{t|0}$ can be very large, causing numerical issues in the Poisson KL terms. The paper addresses this with a reformulation (Equation 92) that avoids explicit computation of large terms.

Training requires approximately 400 GPU-hours on A100s for the OpenWebText model (262B tokens, 163M parameters). TinyStories experiments can run on a single GPU in under 24 hours. The Ï-leaping sampler requires a Poisson sampling implementation that can handle variable rates efficiently.

Code and pretrained weights are available at https://huggingface.co/Jiangxy1117/Neural-CTMC. The implementation uses standard PyTorch with no exotic dependencies. A competent ML engineer could likely reproduce the core method in 1-2 weeks, with another week for optimization and debugging to match paper results.

## Production implementation

**Tech stack**: PyTorch model exported to TensorRT-LLM for serving, with fallback to vanilla PyTorch for unsupported operations. FastAPI service layer with Redis for caching partial generations. The dual-head architecture maps naturally to TensorRT's multi-output graph optimization.

**Data pipeline**: Training data flows through HuggingFace datasets â BPE tokenization â tfrecords for efficient shuffling. Inference pipeline: raw text â GPT-2 tokenizer â padded batches â model â Ï-leaping sampler â detokenization. Reference Gemma-2 model loaded separately for online quality scoring of generated samples.

**Deployment shape**: Online service targeting 100ms P50 latency for 128-token generations. Single A100 40GB handles ~20 QPS at batch size 8 with 32 sampling steps. For cost-sensitive deployments, quantize to INT8 and run on T4s with 10Ã throughput reduction.

**Failure modes in production**: 
- Distribution shift: Monitor exit rate statisticsâif mean rates drift >2Ï from training, trigger retraining
- Degenerate sampling: Detect infinite loops where $\lambda_t^\theta \approx 0$ everywhere, implement timeout and fallback to greedy decoding
- Memory spikes: Jump distribution computation can OOM on long sequencesâimplement gradient checkpointing and sequence chunking
- Numerical instability: Near $t=0$ or $t=T$, implement safe log/exp with clamping

**Evaluation plan**: Offline metrics include perplexity on held-out data and KL from reference model outputs. Online A/B test measures user engagement duration and explicit quality ratings. Critical guardrail: generated text must pass toxicity filter (Perspective API) with <0.1% failure rate. Business KPIs: cost per 1K tokens generated and user retention at day 7.

**Rollout strategy**: Shadow mode for 1 week comparing against existing MDLM baseline â 1% traffic with aggressive monitoring â ramp 10% daily if perplexity degradation <5% â full launch. Instant rollback trigger: >1% toxic content detection rate or >200ms P99 latency.

**Cost back-of-envelope**: At 32 sampling steps and batch 8 on A100, approximately $0.02 per 1K tokens generated. Cost ceiling at $0.10/1K tokens. First lever when breached: reduce sampling steps to 16 and implement speculative decoding with a smaller draft model.

## Related reading

- **Campbell et al. (2022)** "A continuous time framework for discrete denoising models" - Establishes the CTMC path measure framework this work builds upon
- **Sahoo et al. (2024)** "Simple and effective masked diffusion language models" - The MDLM objective emerges as a special case of Neural CTMC's framework
- **Gillespie (1977)** "Exact stochastic simulation of coupled chemical reactions" - Original Ï-leaping algorithm that inspired the sampling decomposition
- **Austin et al. (2021)** "Structured denoising diffusion models in discrete state-spaces" - D3PM introduced discrete diffusion but without the timing/direction decomposition
- **Song et al. (2021)** "Score-based generative modeling through stochastic differential equations" - Continuous diffusion theory that motivates the score-based perspective in discrete settings

## Key equations

- **Rate matrix decomposition**: $R_t(i,j) = \lambda_t(i) \cdot r_t(j|i)$ - Separates exit rate from jump distribution
- **KL factorization**: $\text{KL}(\hat{Q} \| P^\theta) = \int \sum_i q_t(i)[\text{KL}_{\text{Poi}}(\hat{\lambda}_t \| \lambda_t^\theta) + \hat{\lambda}_t \cdot \text{KL}_{\text{Cat}}(\hat{r}_t \| r_t^\theta)]dt$ - Shows timing and direction learn independently  
- **Uniform forward transition**: $q_{t|0}(j|i) = \text{Cat}(j; P_t e_i)$ with $P_t = (1-t/T)I + (t/T)\pi\mathbf{1}^T$ - Closed-form transitions enable efficient training
- **Conditional loss**: $\mathcal{L} = \mathbb{E}[\lambda_t^\theta r_t^\theta - \hat{R}_{t|0}\log(\lambda_t^\theta r_t^\theta/R_t) + K(\hat{R}_{t|0}/R_t)]$ - Tractable objective avoiding marginal quantities