# DossierIQ

**DossierIQ** is an evidence-oriented document investigation application
that extracts entities from documents, identifies supported
relationships between them, and presents the results through an
interactive knowledge graph.

The project is designed to help users inspect *who or what appears in a
document, which supported relationships were detected, and what source
evidence supports each relationship*.

## Current Features

-   **PDF and TXT ingestion** --- extracts text from supported PDF and
    plain-text files.
-   **Named-entity extraction** --- uses spaCy (`en_core_web_sm`) to
    identify entities such as organizations, people, dates, and
    locations.
-   **Entity resolution** --- normalizes entity names and resolves
    matching mentions to canonical entities.
-   **Rule-based relationship extraction** --- identifies relationships
    using explicitly configured text patterns and entity-type
    constraints.
-   **Evidence-backed relationships** --- records the supporting text
    and source-document information for detected relationships.
-   **Knowledge graph construction** --- represents entities and
    directed relationships with NetworkX.
-   **Interactive graph visualization** --- uses PyVis to show entity
    types with distinct colors, directional edges, filters, and hover
    details.
-   **Graph Console** --- lets users select an entity and inspect its
    incoming and outgoing relationships, source documents, and evidence.
-   **Investigation Explorer** --- supports inspection of an entity's
    direct connections and the evidence associated with those
    relationships.
-   **Persistence and retrieval** --- stores investigations in SQLite
    and allows saved investigations to be reopened, with their graph
    reconstructed from stored data.
-   **Streamlit dashboard** --- provides the application interface for
    running and reviewing investigations.

## Current Scope

DossierIQ currently uses a conservative, rule-based approach to
relationship extraction. It detects only relationship patterns that have
been explicitly implemented. It does **not** guarantee detection of
every relationship in a document, and the absence of a displayed
relationship should not be interpreted as proof that no real-world
relationship exists.

**Multi-document processing is planned as a future add-on and is not
presented here as a completed feature.** The current project should be
evaluated against the functionality that has been implemented and
tested.

## Technology Stack

  Component                       Technology
  ------------------------------- -------------------------
  Language                        Python
  Dashboard                       Streamlit
  PDF text extraction             pypdf
  Named-entity recognition        spaCy, `en_core_web_sm`
  Entity and relationship graph   NetworkX
  Interactive graph display       PyVis
  Persistence                     SQLite
  Testing                         Python `unittest`

## Project Structure

The main project modules are organized as follows:

``` text
DossierIQ/
├── app/
│   ├── streamlit_app.py       # Streamlit application
│   └── graph_visualizer.py    # Interactive knowledge graph
├── core/
│   ├── document_loader.py     # PDF/TXT text extraction
│   ├── entity_extractor.py    # Named-entity extraction
│   ├── entity_resolver.py     # Entity normalization/resolution
│   ├── relationship_extractor.py
│   ├── knowledge_graph.py     # Graph construction
│   ├── investigation.py       # Investigation workflow
│   └── investigation_graph.py # Reconstruct saved graph
├── storage/
│   ├── database.py            # SQLite setup/schema
│   ├── investigation_store.py # Persist investigation results
│   └── investigation_retrieval.py
├── data/
│   ├── documents/             # Sample/input documents
│   └── processed/             # Processing artifacts, if used
├── tests/                     # Automated tests
├── .gitignore
└── README.md
```

Some local development files or additional modules may exist in a
working checkout and are not listed above.

## Requirements

-   Python 3.12 (the project has been developed and tested in a Python
    3.12 environment)
-   pip
-   The spaCy English small model, `en_core_web_sm`

## Setup

Run these commands from the project root.

### 1. Create and activate a virtual environment

**Windows PowerShell:**

``` powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks script activation, use Command Prompt instead:

``` bat
.venv\Scripts\activate.bat
```

### 2. Install dependencies

If the repository contains a maintained `requirements.txt`, install from
it:

``` powershell
python -m pip install -r requirements.txt
```

Otherwise, install the currently used runtime packages:

``` powershell
python -m pip install streamlit spacy pypdf networkx pyvis
python -m spacy download en_core_web_sm
```

If spaCy reports that `en_core_web_sm` is missing, run the
model-download command above in the same virtual environment used to
launch the application.

## Run the Application

From the project root:

``` powershell
python -m streamlit run app/streamlit_app.py
```

Streamlit will print a local URL in the terminal. Open that URL in your
browser.

## Typical Workflow

1.  Launch the Streamlit application.
2.  Upload supported PDF or TXT input documents using the interface.
3.  Start an investigation.
4.  Review the investigation overview and extracted entities.
5.  Inspect detected relationships and their supporting evidence.
6.  Explore the interactive knowledge graph. Use the entity-type and
    relationship-type filters to focus the view; isolated entities can
    also be shown or hidden.
7.  Use the Graph Console and Investigation Explorer to inspect an
    entity's connections and source evidence.
8.  Reopen a saved investigation from the dashboard when needed.

The exact controls and available inputs depend on the current version of
the application.

## Relationship Extraction

Relationship extraction is pattern-based. Each supported pattern
specifies a relationship type, direction, and allowed entity types. For
example, implemented patterns include agreement-related relationships
and acquisition relationships.

Because this approach relies on explicit patterns, different wording,
sentence structures, missing entity mentions, or unsupported
relationship types may cause a relationship not to be detected. Add new
patterns only with tests that verify both the relationship and its
direction.

## Data Storage

Investigation results are stored in a local SQLite database, currently
configured by the application under:

``` text
data/dossieriq.db
```

Keep the database file if you want to retain local saved investigations.
Do not commit private or sensitive investigation documents, extracted
content, or database records to a public repository.

## Testing

The project uses Python's `unittest` framework. Run the
relationship-extractor tests with:

``` powershell
python -m unittest tests.test_relationship_extractor -v
```

Run the full test suite from the project root with:

``` powershell
python -m unittest discover -s tests -v
```

The relationship-extractor suite was reported to pass all 38 tests
during development. Test results can change as the code evolves; run the
suite against your current checkout before presenting or submitting the
project.

## Current Limitations

-   Relationship extraction covers only explicitly configured patterns.
-   Some entities may remain isolated because no supported relationship
    was detected for them.
-   Entity recognition and canonicalization can be imperfect,
    particularly for unusual names or ambiguous mentions.
-   Evidence context and source attribution should be checked against
    the original document before relying on a result.
-   Multi-document processing is reserved for future development and
    should not be treated as a completed capability.

## Future Work

Potential future improvements include:

-   Multi-document processing and cross-document entity linking.
-   Broader relationship patterns and stronger relationship validation.
-   Better entity disambiguation and canonicalization.
-   Improved evidence sentence selection and source traceability.
-   Additional graph exploration and filtering features.
-   More representative sample documents and end-to-end regression
    tests.

## Academic Use and Disclaimer

DossierIQ is a student project intended for document-analysis and
investigation-workflow experimentation. Its extracted entities and
relationships are machine-generated and may be incomplete or incorrect.
Verify findings against the original source documents before drawing
conclusions. The application should not be treated as an autonomous
source of factual or legal determinations.

## License

No license has been specified yet. Add a license file before
distributing or accepting external contributions under explicit reuse
terms.
