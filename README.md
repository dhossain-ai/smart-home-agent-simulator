# Smart Home Agent Simulator

A multi-agent smart home request handling project. The system interprets natural-language user requests, discovers available devices and affordances from a smart home simulator, checks active user preferences, and evaluates predicted actions against ground-truth requests.

## Project structure

```text
.
├── simulator_data/              # RDF/Turtle home descriptions and initial state files
├── smart_home_hw/               # Agent, solver, model, and evaluation code
│   ├── environment_manager.py   # EnvironmentManager agent
│   ├── request_solver.py        # RequestSolver strategies
│   ├── evaluation.py            # Evaluation logic
│   ├── llm_client.py            # Optional LLM client
│   ├── models.py                # Shared dataclass models
│   └── run_evaluation.py        # Evaluation entry point
├── homes_config.json
├── preferences.json
├── requests.json
├── smart_home_simulator.py      # FastAPI simulator
├── start_simulator.sh
├── requirements.txt
└── README.md
```

## Setup

Install dependencies:

```bash
pip install -r requirements.txt
```

## Running the simulator

Start the simulator from the repository root:

```bash
python smart_home_simulator.py
```

The simulator runs at:

```text
http://localhost:8080
```

Keep this terminal open while running evaluation.

## Running evaluation

Open a second terminal and run:

```bash
python smart_home_hw/run_evaluation.py
```

The evaluation loads:

- `requests.json`
- `preferences.json`
- simulator data from `simulator_data/`

It evaluates multiple request-solving strategies and prints a metrics table.

## Optional LLM configuration

The code can use an LLM if an API key is configured. Without an API key, the solvers use deterministic fallback parsing where possible.

For OpenAI-compatible usage, set:

```bash
OPENAI_API_KEY=your_api_key_here
```

On PowerShell for the current session:

```powershell
$env:OPENAI_API_KEY="your_api_key_here"
```

## Evaluation metrics

The evaluation reports:

- success rate
- success-or-quantifiable rate
- action F1
- property accuracy
- impossible detection rate
- average duration

Metrics are saved to:

```text
results/evaluation_metrics.json
```

## Notes

- The simulator must be running before evaluation.
- Full Context evaluation can be slow because it fetches complete room, device, affordance, and state information.
- Sequential and semantic strategies are generally faster because they query a smaller part of the environment.