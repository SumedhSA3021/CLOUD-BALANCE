# CloudBalance: Research Literature Review & Analysis
**Document Name:** Summary of Literature Survey Papers  
**Project:** Design and Development of Adaptive Cloud Load Balancing (CloudBalance)  
**Location:** Research_Papers/summaryD1.md  

---

# Paper 1: Nisha Devi et al. (2024)

### Author Identifier & Reference
* **Primary Authors:** Nisha Devi, Sandeep Dalal, Kamna Solanki, Surjeet Dalal, Umesh Kumar Lilhore, Sarita Simaiya, and Nasratullah Nuristani
* **Publication & Citation:** *Artificial Intelligence Review* (Springer), Vol. 57, Article 276, Published September 2024.
* **Title:** *A Systematic Literature Review for Load Balancing and Task Scheduling Techniques in Cloud Computing*
* **File Reference:** Papers/Paper1_Devi2024_Systematic_Literature_Review_Load_Balancing.pdf

---

### 1. Simple Layman Overview
Imagine managing a giant industrial kitchen with dozens of chefs. Orders arrive continuously. If one chef is overwhelmed with complicated orders while three other chefs sit idle, food gets cold, and customers leave angry. 
This paper is a master survey that looks across hundreds of recent cloud research works to answer: *How can cloud systems distribute heavy incoming task loads among available servers so that no single server burns out, energy is saved, and tasks finish as fast as possible?*

### 2. What This Paper Has Done (Key Contributions)
* **Analyzed Over a Decade of Research:** Examined the evolution of task scheduling and load balancing algorithms across global cloud environments.
* **Taxonomy & Classification:** Divided cloud load balancing into two primary categories:
  1. **Static Approaches:** Rules fixed in advance (e.g., Round Robin, Min-Min, Max-Min). They perform poorly under fluctuating, real-world traffic.
  2. **Dynamic Approaches:** Algorithms that evaluate the real-time health and load of nodes before making a decision.
* **Explored Multi-Objective Optimization:** Evaluated algorithms that optimize multiple competing goals simultaneously: minimizing **makespan** (total completion time), reducing response latency, cutting energy consumption, and avoiding Service Level Agreement (SLA) penalties.

### 3. Key Findings & Research Gaps Identified
* **Failure of Static Heuristics:** Traditional algorithms cannot handle modern data spikes (e.g., Internet of Everything / IoT workloads).
* **Trade-Off Challenges:** Improving speed often increases energy consumption; reducing energy can cause bottleneck delays. Hybrid and mathematical techniques that balance multiple parameters are required.
* **Simulation Over-Reliance:** Most published research was conducted only inside simulated tools (like CloudSim) rather than on real cloud platforms.

### 4. Connection to Your Project (CloudBalance)
* Devi et al. proves the necessity of **dynamic, multi-resource load balancing**.
* CloudBalance directly addresses the major research gap identified in this paper by moving beyond simulations and deploying an **adaptive, multi-constraint solver on live Google Cloud Compute Engine VMs**.

---

# Paper 2: Darakhshan Syed et al. (2024)

### Author Identifier & Reference
* **Primary Authors:** Darakhshan Syed, Ghulam Muhammad, and Safdar Rizvi
* **Publication & Citation:** *Intelligent Automation & Soft Computing* (Tech Science Press), Vol. 39, No. 3, pp. 453-480, Published July 2024.
* **Title:** *Systematic Review: Load Balancing in Cloud Computing by Using Metaheuristic Based Dynamic Algorithms*
* **File Reference:** Papers/Paper2_Syed2024_Metaheuristic_Dynamic_Algorithms.pdf

---

### 1. Simple Layman Overview
Standard mathematical formulas can take too long to solve if thousands of cloud tasks arrive every second. To solve this, researchers often use nature-inspired shortcuts (metaheuristics)-such as how ants find the shortest route to food or how birds fly in a flock. This paper systematically reviews how these intelligent algorithms dynamically balance workloads in cloud environments.

### 2. What This Paper Has Done (Key Contributions)
* **Systematic PRISMA Review:** Screened and deeply analyzed 208 high-impact research papers focusing on dynamic load balancing from 2018 to 2024.
* **Comprehensive Algorithm Mapping:** Categorized dynamic metaheuristics into major families:
  * **Swarm Intelligence:** Particle Swarm Optimization (PSO), Ant Colony Optimization (ACO), Artificial Bee Colony (ABC).
  * **Evolutionary Algorithms:** Genetic Algorithms (GA), Differential Evolution.
  * **Physics/Chemistry-based:** Simulated Annealing, Gravitational Search.
* **Performance Metric Benchmarking:** Evaluated these algorithms based on resource utilization, throughput, cost efficiency, fault tolerance, and migration overhead.

### 3. Key Findings & Research Gaps Identified
* **High Algorithmic Overhead:** While metaheuristic algorithms find good solutions, complex algorithms (like pure Genetic Algorithms) suffer from slow convergence times, making them difficult to run in real-time online dispatchers.
* **Resource Imbalance:** Many algorithms optimize solely for CPU time, neglecting memory (RAM) or network bandwidth, leading to sudden Out-Of-Memory crashes.
* **Need for Hybridization:** Combining fast linear mathematical models with dynamic metrics gives far more predictable results than stochastic (randomized) algorithms alone.

### 4. Connection to Your Project (CloudBalance)
* It justifies why CloudBalance chooses **Google OR-Tools**: OR-Tools provides the sub-millisecond execution speed needed for real-time dispatching while evaluating multiple resource dimensions (CPU + RAM) simultaneously, avoiding the convergence delays of heavy metaheuristics.

---

# Paper 3: O. L. Abraham et al. (2024)

### Author Identifier & Reference
* **Primary Authors:** O. L. Abraham, M. A. Ngadi, J. M. Sharif, and M. K. M. Sidik
* **Publication & Citation:** *IEEE Access*, Vol. 12, pp. 138252-138279, 2024.
* **Title:** *Task Scheduling in Cloud Environment - Techniques, Applications, and Tools: A Systematic Literature Review*
* **File Reference:** Papers/Paper3_Abraham2024_Task_Scheduling_Review.pdf

---

### 1. Simple Layman Overview
Scheduling tasks in the cloud is like managing airport air traffic control: flights (tasks) arrive with different fuel levels (deadlines) and passenger counts (resource needs), and you have a fixed number of runways (VMs). One bad decision causes cascading delays across the entire network. This paper evaluates the state-of-the-art tools, constraints, and scheduling methods used in modern cloud computing.

### 2. What This Paper Has Done (Key Contributions)
* **Analyzed 2021-2024 Literature:** Reviewed recent breakthroughs in task scheduling frameworks across enterprise clouds.
* **Formalized Scheduling Constraints:** Detailed the exact operational constraints that schedulers must obey:
  * **Deadlines and Priority:** Critical tasks must execute before lower-priority background tasks.
  * **Resource Capacities:** Hard physical limits on RAM, processor cores, and storage.
  * **Cost & Budget Limits:** Minimizing billable VM compute-hours in public clouds (like AWS and GCP).
* **Tool & Environment Survey:** Surveyed evaluation platforms, showing that over 85% of research relied on CloudSim/CloudSim Plus, while very few implemented systems on commercial public cloud infrastructure.

### 3. Key Findings & Research Gaps Identified
* **No Free Lunch:** The authors conclude that no single scheduling algorithm is universally superior for all cloud workloads. Performance depends heavily on task arrival dynamics and resource monitoring accuracy.
* **Uneven Workload Degradation:** Inadequate load balancing directly causes VM resource starvation, unacceptably high makespan, and financial loss due to SLA violations.
* **Call for Practical Implementation:** Schedulers must be verified on commercial cloud virtual machines to measure actual operating system context switching and network transport overhead.

### 4. Connection to Your Project (CloudBalance)
* Directly supports Member 2's **constraint formulation**: enforcing single-assignment rules and hard CPU/RAM thresholds in Google OR-Tools.
* Validates your architectural decision to test on **live Google Cloud Compute Engine Ubuntu VMs** instead of an artificial simulator.

---

# Paper 4: Nidhika Chauhan et al. (2024)

### Author Identifier & Reference
* **Primary Authors:** Nidhika Chauhan, Navneet Kaur, Kamaljit Singh Saini, Sahil Verma, Abdulatif Alabdulatif, Ruba Abu Khurma, Maribel Garcia-Arenas, and Pedro A. Castillo
* **Publication & Citation:** *Computer Systems Science and Engineering* (CSSE), Vol. 48, No. 3, 2024.
* **Title:** *A Systematic Literature Review on Task Allocation and Performance Management Techniques in Cloud Data Center*
* **File Reference:** Papers/Paper4_Chauhan2024_Task_Allocation_Data_Center.pdf

---

### 1. Simple Layman Overview
A cloud data center has thousands of physical machines hosting virtual machines. If tasks are allocated blindly, certain racks get dangerously hot and consume excessive electricity while other machines sit nearly empty. This paper investigates how to allocate incoming tasks while simultaneously managing the overall health, performance, and monitoring of the data center.

### 2. What This Paper Has Done (Key Contributions)
* **Massive Comparative Study:** Analyzed **463 task allocation papers** and **480 performance management papers**.
* **Categorized Task Allocation into 3 Pillars:**
  1. *Resource Allocation:* Provisioning the right VM size for incoming workloads.
  2. *Load Balancing:* Distributing tasks to maintain even utilization across nodes.
  3. *Job Scheduling:* Determining the exact sequence and timing of execution.
* **Categorized Performance Management into 7 Strategies:** Real-time monitoring and control, power/energy management, resource utilization optimization, QoS enforcement, fault tolerance, VM live migration, and network latency management.

### 3. Key Findings & Research Gaps Identified
* **Closed-Loop Feedback is Mandatory:** Allocation cannot be an isolated, one-way decision. It requires continuous monitoring telemetry fed directly back into the allocator.
* **Decoupled Architecture Works Best:** High-performing cloud systems separate the **monitoring layer** from the **decision/optimization layer** so monitoring delays do not stall task execution.

### 4. Connection to Your Project (CloudBalance)
* Perfectly aligns with CloudBalance's **modular division**:
  * **Module 1 (Monitoring):** Handles real-time telemetry via psutil + Redis.
  * **Module 2 & 3 (Member 2):** Uses the monitored state to drive optimal task allocation via Google OR-Tools.
  * **Module 5:** Live observability dashboard for performance tracking.

---

# Paper 5: N. Elsakaan & K. Amroun (2024)

### Author Identifier & Reference
* **Primary Authors:** N. Elsakaan and K. Amroun
* **Publication & Citation:** *The Journal of Supercomputing* (Springer), Vol. 80, No. 9, pp. 1-41, 2024.
* **Title:** *A Novel Multi-Level Hybrid Load Balancing and Tasks Scheduling Algorithm for Cloud Computing Environment*
* **File Reference:** Papers/Paper5_Elsakaan2024_MultiLevel_Hybrid_Scheduling.pdf

---

### 1. Simple Layman Overview
When thousands of IoT smart devices (cameras, sensors, smartphones) send data spikes all at once, typical cloud schedulers freeze or crash under the sudden avalanche. The authors proposed a clever two-step (two-tier) filter: first, group similar servers together using machine learning; second, assign the easiest tasks coarsely, and use an intelligent algorithm to fine-tune only the heavy assignments.

### 2. What This Paper Has Done (Key Contributions)
* **Proposed a Two-Tier Hybrid Architecture:**
  1. **Tier 1 (Clustering Stage):** Uses **K-Means Clustering** to categorize servers within a data center based on their current utilization levels (e.g., Low, Medium, High load clusters).
  2. **Tier 2 (Coarse Scheduling):** Distributes incoming batches of tasks across non-overloaded clusters using a fast Round-Robin method.
  3. **Tier 3 (Fine-Grained Scheduling):** Inside each chosen cluster, uses a **Genetic Algorithm (GA)** to fine-tune the exact task-to-VM placement.
* **Evaluated on CloudSim Plus:** Tested against extreme, unpredictable IoT traffic bursts.

### 3. Key Findings & Reported Results
* **Shortened Makespan:** Total time required to finish heavy task batches dropped significantly compared to single-tier algorithms.
* **Fewer Migrations & SLA Violations:** Pre-filtering overloaded clusters prevented tasks from landing on servers that were about to run out of memory.

### 4. Connection to Your Project (CloudBalance)
* **Handling Bursty Traffic:** Elsakaan & Amroun's focus on handling sudden traffic spikes directly validates your **Poisson Arrival Generator (Module 2)**.
* **Why CloudBalance is Leaner:** While their method used complex multi-tier clustering and Genetic Algorithms (which have higher computational overhead), CloudBalance achieves safe, multi-resource load distribution in a single step using **Google OR-Tools Mixed-Integer Linear Programming**, executing directly against live GCP Compute Engine instances.

---

### Quick Comparison Matrix for Presentations & Viva

| Paper | Focus Area | Technique Used | Cloud Environment | Relevance to CloudBalance |
| :--- | :--- | :--- | :--- | :--- |
| **Devi et al. (2024)** | Comprehensive SLR on Load Balancing & Scheduling | Literature review of heuristics & ML methods | Simulation Survey | Confirms need for multi-objective, dynamic load balancing |
| **Syed et al. (2024)** | Dynamic Metaheuristics & Swarm Intelligence | Review of PSO, ACO, Genetic Algorithms | Simulation Survey | Shows metaheuristics can be slow; supports fast MILP solvers |
| **Abraham et al. (2024)** | Task Scheduling & Operational Constraints | Review of deadlines, budget & capacity constraints | Simulation Survey | Validates CloudBalance's CPU/RAM mathematical constraints |
| **Chauhan et al. (2024)** | Data Center Task Allocation & Performance | Classification of allocation & monitoring systems | Data Center Survey | Supports decoupling monitoring (Redis) from optimization (OR-Tools) |
| **Elsakaan & Amroun (2024)** | Hybrid Multi-Level Scheduling for IoT Spikes | K-Means Clustering + Genetic Algorithm | CloudSim Plus | Demonstrates handling bursty traffic (like our Poisson model) |
