# **Architectural Design of a Multi-Agent System for University Admission Counseling in Vietnam**

## **Context and the Urgency of Restructuring Admission Counseling Systems**

The higher education landscape in Vietnam, particularly the admission process, is undergoing profound and continuous transformations with comprehensive adjustments from state management agencies. Practice shows that applying to top-tier universities in the Hanoi area—such as Hanoi University of Science and Technology (HUST), National Economics University (NEU), Foreign Trade University (FTU), Vietnam National University (VNU), or Hanoi Medical University—requires candidates and parents to process a massive, complex, and heterogeneous volume of information. Fundamental changes in **Circular No. 06/2025/TT-BGDĐT** by the Ministry of Education and Training (MoET) have completely altered the 2025 admission landscape. Key changes include the total abolition of "early admission" methods, the requirement for academic transcripts to be based on full Grade 12 data, and strict limits on bonus points not exceeding 10% of the maximum total score.

Beyond MoET regulations, each institution autonomously issues its own admission schemes with different structures, terminologies, and evaluation methods. Schools use multiple channels for announcements: from official websites and detailed PDF files to quick posts on social media or official admission fanpages. This fragmentation creates a data ecosystem characterized by multiple formats, high **freshness volatility**, and frequent internal **conflicts**. A fanpage post might update the latest quotas approved by the admission council, while the PDF on the website remains outdated, leading to knowledge inconsistency.

To automate admission counseling, traditional Artificial Intelligence (AI) approaches often use basic **RAG (Retrieval-Augmented Generation)** systems or FAQ chatbots based on a **Single-Agent** architecture. However, these architectures reveal fatal weaknesses when facing the complexity of Vietnamese higher education. Standard RAG systems tend to extract information randomly based on vector similarity without understanding the hierarchical authority of document sources, leading to advice based on obsolete regulations. Single-agent architectures lack task decomposition and **cross-verification** mechanisms, making them prone to "hallucination" or providing misleading information when handling multi-step logical chains.

The table below illustrates the decisive differences between Single-Agent systems and Multi-Agent Systems (MAS) in the context of complex admission data:

| Comparison Criteria | Single-Agent System | Multi-Agent System (MAS) |
| :--- | :--- | :--- |
| **Complexity & Task Division** | Simple; a single agent handles everything from extraction to counseling. | Highly decomposed into specialized agents (Extraction, Validation, Reasoning). |
| **Conflict Handling** | Entirely dependent on the LLM; prone to hallucinations or random info selection. | Uses layered conflict resolution (Layer III) through debate and policies. |
| **Scalability** | Limited; difficult to fine-tune when adding new multi-modal data sources. | High flexibility; easy to plug-in new agent modules. |
| **Robustness & Control** | Prone to collapse if the agent fails at a single reasoning step. | Orchestrated coordination with feedback loops for self-correction. |

To thoroughly address these challenges, this report presents a systematic **Multi-Agent Reasoning Architecture**. This architecture is divided into three core processing streams: **Pipeline Ingestion** (Data Consumption and Standardization), **Pipeline Conflict Handling**, and **Pipeline Advisory**. The entire system is governed by **Policy-driven Orchestration** mechanisms, ensuring every piece of input has a clear provenance and every counseling decision strictly adheres to current legal frameworks.



## **Database Design and Extended Knowledge Graph (KG)**

Before diving into the agent network's operation, a solid knowledge representation foundation must be established. University admission data is highly structured yet contains myriad polymorphic relationships. Traditional **Relational Databases** based on **Entity-Relationship Diagrams (ERD)** typically partition data into rigid tables like Students, Courses, Departments, and Majors. While good for administrative data, this model lacks the flexibility needed to process unstructured knowledge collected continuously from the web. Therefore, the proposed architecture utilizes a **Knowledge Graph (KG)**—using platforms like Neo4j—to serve as the **Shared Graph Memory** for all agents.

The Knowledge Graph stores entities as **Nodes** (e.g., Hanoi University of Science and Technology, Computer Science Major, International Certificate Admission Method, IELTS 6.5) and relationships as **Edges** (e.g., BELONGS_TO, REQUIRES, CONVERTS_TO). The advantage of a KG lies in allowing agents to easily retrieve context using graph languages like Cypher, thereby reconstructing the "big picture" without losing multi-dimensional links.

To ensure data integrity and resolve conflicts, the KG is partitioned into two main storage zones:

1.  **Append-Only Evidence Log:** A raw storage area that accepts all information extracted from the internet. Each data node is tagged with granular metadata: source URL, publication time, extraction time, and **Source Authority** classification. It acts as an immutable ledger, allowing the system to trace back the origin of any information.
2.  **Immutable Rulebook:** A refined graph partition acting as the **Single Source of Truth** for counseling. Events, figures, and regulations are only updated here after passing through the validation and conflict resolution network. Top-layer agents only query data from the Rulebook.
3.  **Shared Agent Memory:** A temporary workspace where agents store intermediate states, hypotheses, and detected errors, preventing context loss during task handovers.

Data exchanged between the graph and agents is strictly standardized using **JSON (JavaScript Object Notation)**, allowing for the clear representation of multi-level admission policies (e.g., language certificates combined with exam scores).

## **Layer I: Pipeline Ingestion (Collection and Normalization)**

Pipeline Ingestion is the system's first line of defense, operating like an automated collection assembly line. This process is more than simple web scraping; it is a sophisticated system for parsing unstructured text, handling multi-modality, and transforming it into programmable semantic structures.

### **1. Extraction Agent**
The input consists of thousands of unstructured documents: press releases, 50-page university PDFs, and short social media posts. The **Extraction Agent** digitizes these materials using Large Language Models (LLMs) combined with **Named Entity Recognition (NER)** and **Relationship Extraction (RE)** optimized for the Vietnamese language. It identifies core objects like university names, industry codes, subject combinations (A00, D01, etc.), and sub-requirements, distinguishing between "floor marks" (minimum quality threshold) and "benchmark marks" (historical admission scores).

### **2. Normalization Agent**
Raw data is often chaotic. One university might call a method "Integrated Admission" while another uses a different term. Furthermore, universities use different scoring scales (e.g., converting IELTS to a 10-point scale vs. a 100-point scale). The **Normalization Agent** performs **Schema Alignment**, mapping local terms to a **Canonical Taxonomy**. It also handles mathematical normalization, converting various grading schemes into unified logic functions within JSON to support automated score calculation.



### **3. Validation Agent**
Even perfectly structured data can contain logical or policy flaws. The **Validation Agent** performs **rule-based evaluation** against the latest legal frameworks. For instance, per Circular 06/2025, bonus points must not exceed 10% of the maximum score. If a school’s scheme requires adding 4 points to a 30-point scale, the Validation Agent flags this as a mathematical violation. It also ensures subject combinations include Math or Literature with a weight of at least 25%, as mandated by law.

### **4. Conflict Detection Agent**
Building **Large Knowledge Graphs** inevitably leads to overlap. The **Conflict Detection Agent** monitors internal inconsistencies without deciding which is correct. If a new entry states a quota of 350 for a major while the Rulebook says 300, a **field-level conflict** is triggered. The agent packages the context—old node, new node, sources, and timestamps—into a **Conflict Ticket** for Layer III.

---

## **Layer III: Pipeline Conflict Handling**

Information conflict is a classic problem that weakens LLMs. In admissions, conflicts often reflect real-time strategic changes by institutions. Resolution cannot rely on simple probability.

| Conflict Taxonomy | Cause | Proposed Strategy |
| :--- | :--- | :--- |
| **Freshness Conflict** | New regulations invalidate old ones (e.g., 2024 vs. 2025). | **Temporal Decay**; prioritize the latest timestamp. |
| **Authority Conflict** | Media reports differ from official university portals. | **Source Hierarchy**; official websites override secondary sources. |
| **Ambiguity Conflict** | Two departments of the same school provide different figures. | **Agent Debate**; multi-modal verification and "Uncertainty" flagging. |

### **1. Evidence Agent**
Acts as a data investigator, retrieving the full chain of original information from the **Evidence Log** to restore context, including timestamps and provenance.

### **2. Comparison Agent**
Analyzes the evidence dossier using **Source Authority Ranking**. It weights MoET Circulars highest, followed by `.edu.vn` websites, verified fanpages, and finally secondary news articles.

### **3. Resolution Agent**
Employs **LLM-based debate mechanisms** or multi-agent negotiation protocols to reach a verdict. It must provide an **explainable rationale** for its choice.

### **4. Decision Policy / Orchestrator**
The highest governance layer. If confidence is high ($P > 0.95$), it authorizes an update to the **Immutable Rulebook**. If the conflict is irreconcilable, the data is stored in the KG with an `UNCERTAIN_FACT` tag, prompting a risk warning during counseling.

---

## **Layer II: Pipeline Advisory (Personalized Counseling)**

With a clean Knowledge Graph, the system provides its core value: admission counseling.

### **1. Profile Agent**
Interacts with students via an **adaptive prompting** interface to build a **Multidimensional Student Vector**: demographics, Grade 12 transcripts, language certificates, career interests, and financial capacity. It uses **Machine Learning** (regression models and matrix factorization) to predict expected exam scores for students who haven't yet taken the national finals.

### **2. Retrieval Agent**
Unlike standard RAG, this agent uses **Deterministic Graph Traversal**. It translates the student's JSON profile into **Cypher queries** to prune thousands of majors, instantly removing options where the student fails to meet hard constraints (e.g., missing prerequisite subjects or failing the 25% Math/Literature weight rule).



### **3. Reasoning Agent**
The analytical "brain." It calculates admission probabilities and builds strategies. It classifies majors into three categories:
* **Safe:** Probability > 90%
* **Target:** Probability 60-90%
* **Reach:** Probability < 60%

### **4. Policy Agent**
Ensures the strategy is legally sound. If the Reasoning Agent suggests a path relying on early admission (now banned before May 5th, 2025), the **Policy Agent** vetoes it.

### **5. Explanation Agent**
Translates complex calculations into natural, friendly language. It explains *why* a school is a high risk or *why* a specific certificate is a major advantage. It also highlights `UNCERTAIN_FACT` risks, advising the user to contact the school directly for verification where data is ambiguous.

---

## **Orchestration Patterns and Practical Application**

The power of MAS comes from **Orchestration**. This architecture implements the **Model Context Protocol (MCP)** to ensure all agents see a consistent semantic context in Neo4j.

### **Multi-Agent Topologies**
1.  **Chain of Command (Hierarchical):** Used in Ingestion and Conflict Handling. Data must flow linearly (Extraction $\rightarrow$ Normalization $\rightarrow$ Validation). A **Supervisor Agent** halts the chain if a step fails to prevent KG pollution.
2.  **Cooperative Network (P2P):** Used in the Advisory Layer. Counseling is iterative. If the Reasoning Agent needs more data, it can ask the Profile Agent to prompt the user for additional info without restarting the entire session. This **graph-based workflow** allows for stateful, human-like interaction.

## **Conclusion**

The Vietnamese university admission landscape—especially for top-tier schools—is defined by strict MoET standards, autonomous institutional diversity, and high-frequency data noise. Simple chatbots are insufficient.

This **Multi-Agent System** architecture offers a methodological revolution. By decomposing tasks into specialized ingestion, conflict resolution, and advisory layers—supported by a Knowledge Graph—the system provides a service that is not only reliable and personalized but also legally compliant and transparent. This model serves as a blueprint for complex knowledge management in the era of generative AI.