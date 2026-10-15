# DossierIQ — Document Intelligence & Knowledge Graph Investigation

**DossierIQ** is a Python-based document intelligence system that extracts named entities, identifies configured relationships, and builds an interactive knowledge graph to support evidence-based investigations across documents.

It transforms unstructured text into structured entity and relationship records, helping users explore connections and trace each detected relationship back to its source document and supporting evidence.

## Overview

Investigating documents manually can make it difficult to identify relevant entities, discover relationships, and keep track of supporting evidence.

DossierIQ streamlines this process through a modular NLP pipeline, a directed knowledge graph, and a Streamlit dashboard. Users can upload documents, inspect extracted information, visualize relationships, and save investigations for later review.

## Key Features

- **Document ingestion:** Load TXT and text-based PDF documents.
- **Named Entity Recognition:** Extract entities using spaCy's NLP pipeline.
- **Entity resolution:** Normalize entity names and resolve mentions using entity-name and entity-type matching.
- **Rule-based relationship extraction:** Detect supported relationships using configured textual patterns.
- **Knowledge graph construction:** Represent entities as nodes and detected relationships as directed edges using NetworkX.
- **Evidence-backed relationships:** Retain supporting text and source-document information for detected relationships.
- **Interactive visualization:** Explore the knowledge graph through a PyVis-based visualization.
- **Investigation Explorer:** Inspect an entity's direct relationships and the evidence associated with them.
- **Investigation persistence:** Store and reopen saved investigations using SQLite.
- **Automated tests:** Validate core processing, graph construction, database operations, and investigation retrieval.

## Technology Stack

| Component | Technology |
|---|---|
| Language | Python |
| User interface | Streamlit |
| Natural Language Processing | spaCy |
| Entity extraction model | `en_core_web_sm` |
| Knowledge graph | NetworkX |
| Interactive graph visualization | PyVis |
| Database | SQLite |
| PDF processing | pypdf |
| Testing | Python `unittest` |

## System Architecture

DossierIQ follows a modular processing architecture.

1. **Document loading:** Read supported files and extract their text and metadata.
2. **Entity extraction:** Identify named entities and retain their contextual information.
3. **Entity resolution:** Normalize entity names and group matching mentions by name and entity type.
4. **Relationship extraction:** Apply configured patterns to identify supported relationships between entities.
5. **Knowledge graph construction:** Build a directed multigraph containing entity nodes and relationship edges.
6. **Result presentation:** Display document information, extracted entities, relationships, evidence, and graph visualizations.
7. **Persistence:** Save investigation records in SQLite so they can be reopened later.

### Processing Workflow

```text
TXT / Text-Based PDF
         |
         v
   Document Loader
         |
         v
 Named Entity Recognition
         |
         v
   Entity Resolution
         |
         v
Rule-Based Relationship Extraction
         |
         v
  Knowledge Graph
         |
         v
   Streamlit Dashboard
      /          \
     v            v
Interactive     Evidence &
Graph Explorer  Relationship Tables
         |
         v
 SQLite Persistence
 (Save / Retrieve)
```

The workflow illustrates the logical processing stages. SQLite persistence is used when an investigation is saved; it is not a mandatory step for every displayed result.

## Project Structure

```text
DossierIQ/
├── app/
│   ├── streamlit_app.py
│   └── graph_visualizer.py
├── core/
│   ├── document_loader.py
│   ├── entity_extractor.py
│   ├── entity_resolver.py
│   ├── pipeline.py
│   ├── knowledge_graph.py
│   ├── investigation.py
│   ├── investigation_graph.py
│   └── relationship_extractor.py
├── storage/
│   ├── database.py
│   ├── investigation_store.py
│   └── investigation_retrieval.py
├── data/
│   └── documents/
│       ├── sample.txt
│       └── sample.pdf
├── tests/
├── requirements.txt
├── .gitignore
└── README.md
```

The structure above highlights the principal modules. Additional initialization files and test modules are present in the repository.

## Getting Started

### Prerequisites

- Python 3.12 recommended
- Git
- pip

### 1. Clone the repository

```bash
git clone https://github.com/vansh-13042005/DossierIQ.git
cd DossierIQ
```

### 2. Create a virtual environment

**Windows PowerShell:**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell prevents activation, use the Python executable inside `.venv` directly or follow your local Python environment policy.

### 3. Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Ensure that the spaCy English model is available:

```bash
python -m spacy download en_core_web_sm
```

### 4. Launch the application

From the repository root, run:

```bash
python -m streamlit run app/streamlit_app.py
```

Streamlit will provide a local URL in the terminal. Open that URL in your browser.

### 5. Run an investigation

1. Upload one or more supported TXT or text-based PDF files.
2. Start a new investigation.
3. Review the document summary and extracted entities.
4. Inspect detected relationships and their supporting evidence.
5. Explore the interactive knowledge graph.
6. Save the investigation if you want to reopen it later.

The repository includes sample documents under `data/documents/` for initial exploration.

## Testing

DossierIQ includes automated tests for its core modules.

Run the test suite from the project root:

```bash
python -m unittest discover -s tests -v
```

Use the output from your current environment as the authoritative test result. The number of passing tests may change as the project evolves.

## Important Design Decisions

### Rule-Based Relationship Extraction

DossierIQ uses configured relationship patterns rather than unrestricted semantic inference. A relationship is detected only when the text matches a supported pattern and the relevant entity constraints are satisfied.

This approach makes the extraction logic explicit and testable, but its coverage depends on the patterns implemented.

### Entity Resolution

Entity mentions are normalized and compared using their names and entity types. This helps consolidate matching mentions, but it does not guarantee that every spelling variation, alias, or ambiguous name will be resolved correctly.

### Evidence and Traceability

Detected relationships retain supporting text and source-document information. This allows users to inspect why a relationship appears in the graph rather than relying solely on a visual connection.

## Limitations

- **Input formats:** The current loader supports TXT and text-based PDFs; scanned, image-only PDFs are not automatically OCR-processed.
- **Entity extraction:** spaCy may miss entities, classify them incorrectly, or identify irrelevant mentions.
- **Relationship coverage:** Only configured relationship patterns are detected.
- **Entity resolution:** Name normalization and entity-type matching cannot reliably resolve every alias or ambiguous identity.
- **Graph completeness:** The graph contains only the entities and relationships extracted by the implemented pipeline.
- **Evidence interpretation:** Supporting text is presented for inspection; its presence does not guarantee that the extracted relationship is factually correct.

## Future Work

Potential enhancements include:

- More robust cross-document entity resolution and alias handling.
- Expanded relationship patterns and extraction coverage.
- Confidence scoring and stronger evidence validation.
- OCR support for scanned documents.
- Graph filtering and improved exploration for larger investigations.
- Investigation export and richer reporting.
- Additional evaluation using manually annotated documents and relationship-level metrics.

These are potential extensions, not claims about currently implemented functionality.

## Intended Use

DossierIQ is an academic mini-project demonstrating document processing, NLP, entity resolution, rule-based information extraction, graph representation, evidence traceability, and persistence.

It is intended as an investigative aid for exploring extracted information. Its outputs should be reviewed against the original documents before being used to make consequential decisions.

## Author

**Vansh Tomar**

B.Tech — Computer Science and Engineering (Artificial Intelligence and Machine Learning)

Meerut Institute of Engineering and Technology (MIET), Meerut

- GitHub: [@vansh-13042005](https://github.com/vansh-13042005)
- Project Repository: [DossierIQ](https://github.com/vansh-13042005/DossierIQ)

---

*DossierIQ — From unstructured documents to traceable entity relationships.*