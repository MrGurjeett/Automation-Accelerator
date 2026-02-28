# Agentic AI Framework Diagrams

## Architecture Diagram
This diagram shows the main components, classes, and their relationships within the AI subsystem.

```mermaid
graph TD
  %% Main Orchestration
  O[AgentOrchestrator] --> IA[IntentAgent]
  O --> PA[PlannerAgent]
  O --> EA[ExecutionAgent]
  
  %% Configuration
  C[AIConfig] --> C_AZ[AzureOpenAISettings]
  C --> C_RAG[RAGSettings]
  O --> C
  
  %% Clients
  O --> AOC[AzureOpenAIClient]
  AOC -.->|API Calls| Azure[Azure OpenAI Service]
  
  %% RAG Subsystem
  subgraph RAG [Retrieval-Augmented Generation]
    R[Retriever] --> ES[EmbeddingService]
    ES --> AOC
    R --> VS{Vector Store}
    
    VS_I[InMemoryVectorStore] -.-> VS
    VS_P[PersistentInMemoryVectorStore] -.-> VS
    VS_Q[QdrantVectorStore] -.-> VS
    
    DL[DocumentLoader] --> TC[TextChunker]
    TC --> ES
    TC --> VS
  end
  O --> R
  O --> DL
  O --> TC
  
  %% Generators
  subgraph Generation [CodeGen Generators]
    FG[FeatureGenerator] --> AOC
    SG[StepGenerator] --> AOC
    FG -.-> ON[OutputNormalizer]
    SG -.-> ON
  end
  O --> FG
  O --> SG
  
  %% Data Flow Examples
  User[/User Intent/Query/] --> O
  O -->|Classifies Intent| IA
  O -->|Plans Execution| PA
  O -->|Routes Calls| EA
  
  EA --> |Search Context| R
  R --> |Returns Context| FG
  FG -->|Generates Scenario| GeneratedFeature[Feature File]
  SG -->|Generates Definitions| GeneratedSteps[Step Definition File]

  %% Styling
  classDef orchestrator fill:#f9f,stroke:#333,stroke-width:2px;
  classDef agent fill:#bbf,stroke:#333,stroke-width:1px;
  classDef rag fill:#dfd,stroke:#333,stroke-width:1px;
  classDef generator fill:#fdf,stroke:#333,stroke-width:1px;
  classDef config fill:#eee,stroke:#333,stroke-width:1px;
  classDef external fill:#ffd,stroke:#333,stroke-width:2px,stroke-dasharray: 5 5;

  class O orchestrator;
  class IA,PA,EA agent;
  class R,ES,VS,DL,TC rag;
  class FG,SG generator;
  class C,C_AZ,C_RAG config;
  class Azure,User external;
```

## System Flow Diagram
This sequence diagram outlines the pipeline workflow from an external UI recording or user input, down through RAG and code generation.

```mermaid
sequenceDiagram
    actor User as User/CLI
    participant O as AgentOrchestrator
    participant IA as IntentAgent
    participant R as Retriever
    participant VS as VectorStore
    participant FG as FeatureGenerator
    participant SG as StepGenerator
    
    User->>O: Execute command (e.g. stage4_enhance)
    activate O
    
    O->>IA: Analyze Input/Intent
    activate IA
    IA-->>O: Return Intent (e.g. generate_feature)
    deactivate IA
    
    O->>R: Retrieve Relevant Context
    activate R
    R->>VS: Search Vectors (similarity)
    activate VS
    VS-->>R: Return Top K Documents
    deactivate VS
    R-->>O: Return Formatted Context Strings
    deactivate R
    
    O->>FG: Generate Feature File
    activate FG
    FG->>FG: Send Context + Intent to LLM
    FG-->>O: Return Gherkin Scope/Text
    deactivate FG
    
    O->>SG: Generate Step Definitions
    activate SG
    SG->>SG: Formulate Pytest-BDD matching
    SG-->>O: Return Python Step Source
    deactivate SG
    
    O-->>User: Save Files / Pipeline Output
    deactivate O
```