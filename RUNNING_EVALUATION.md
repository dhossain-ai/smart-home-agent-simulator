# Running the Evaluation

## Prerequisites

1. **Start the SmartHome Simulator** (in one terminal):
   ```bash
   bash start_simulator.sh
   ```
   The simulator will load 32 homes and listen on http://localhost:8080.

2. **Environment Setup** (optional, for real strategies):
   ```bash
   cp .env.example .env
   # Edit .env and add your OpenAI API key if using real LLM strategies
   export OPENAI_API_KEY=sk-...
   ```

## Running the Dummy Solver Test

The dummy solver demonstrates agent communication without needing the simulator or API keys:

```bash
cd smart_home_hw
python run_evaluation.py
```

### Output Structure

```
======================================================================
SmartHome Homework Evaluation
======================================================================

Loaded 36 requests
Loaded 3 preferences
Simulator URL: http://localhost:8080
✓ EnvironmentManager agent started (message handler thread running)
✓ DummyRequestSolver created
  (Use VERBOSE_AGENTS=1 to see agent communication details)

======================================================================
Running evaluation...
======================================================================
[1/36] home59_one_526                 — False
[5/36] home1_one_102                  — True
...

======================================================================
Results
======================================================================
{
  "total_tests": 36,
  "successful_tests": 1,
  ...
}

======================================================================
Summary
======================================================================
Success Rate: 2.8%
Action F1: 4.8%
Property Accuracy: 100.0%
...

======================================================================
Shutting down agents...
======================================================================
✓ EnvironmentManager agent stopped
```

## Verbose Agent Communication

To see detailed agent communication logs:

```bash
VERBOSE_AGENTS=1 python run_evaluation.py
```

This shows the request-response flow between DummyRequestSolver and EnvironmentManager:

```
[DummyRequestSolver] Processing request: home59_one_526
[DummyRequestSolver] Home: home12, Room: guest_bedroom
[DummyRequestSolver] → Requesting artifacts in guest_bedroom
[EnvironmentManager] ← Request from RequestSolver: get_artifacts_in_room(...)
[EnvironmentManager] → Response to RequestSolver: get_artifacts_in_room = [...]
[DummyRequestSolver] ← Received N artifact(s)
[DummyRequestSolver] → Requesting affordances for guestBedroomDehumidifiers
[EnvironmentManager] ← Request from RequestSolver: get_artifact_affordances(...)
[EnvironmentManager] → Response to RequestSolver: get_artifact_affordances = {...}
[DummyRequestSolver] ← Received affordance info
[DummyRequestSolver] → Reading property: mode
[EnvironmentManager] ← Request from RequestSolver: read_property(...)
[EnvironmentManager] → Response to RequestSolver: read_property = {'value': 'manual'}
[DummyRequestSolver] ← Current mode value: manual
[DummyRequestSolver] → Returning hardcoded action
```

## What Happens During Evaluation

### For Each Request (36 total):

1. **DummyRequestSolver.solve()**:
   - Sends request to EnvironmentManager for artifact info
   - Receives responses via message passing
   - Returns hardcoded action

2. **Evaluation Harness**:
   - Executes the predicted action at simulator
   - Reads property values to verify results
   - Resets home state for next request
   - Computes metrics (success, F1, property accuracy, etc.)

3. **Metrics Accumulation**:
   - Tracks matched vs. missed actions
   - Tracks property verification results
   - Tracks error_input detection

### Expected Results for DummyRequestSolver

- **Success Rate**: ~2.8% (only 1 request matches the hardcoded action)
- **Action F1**: Very low (correct on only home12)
- **Property Accuracy**: High when action executes
- **Full metrics table**: Shows where dummy strategy fails

## Troubleshooting

### "Connection refused" on reset endpoint
- Simulator is not running
- **Fix**: Run `bash start_simulator.sh` first

### "Agent communication timeout"
- EnvironmentManager thread not responding
- **Fix**: Check verbose logs with `VERBOSE_AGENTS=1`

### "Method not found" errors in EnvironmentManager
- Method is called but not implemented
- **Expected**: `get_artifacts_in_room`, `get_artifact_affordances` raise NotImplementedError (student implementations)
- **Working**: `read_property` returns actual values

### High property accuracy but low success rate
- Actions are being read (property values are correct)
- But predicted actions don't match ground truth
- **Expected**: DummyRequestSolver always returns same action

## Agent Communication Protocol

See [AGENT_COMMUNICATION.md](AGENT_COMMUNICATION.md) for details on:
- How agents communicate via message passing
- Request-response protocol
- Message broker routing
- Adding new agent methods

## Next Steps

After testing the dummy solver:

1. Implement `FullContextSolver` (Strategy 1)
   - Override `solve()` method in a subclass
   - Call EnvironmentManager methods as needed
   - Return list of ActionOutput objects

2. Implement `SequentialSolver` (Strategy 2)
   - Iteratively discover relevant affordances
   - Make fewer EnvironmentManager requests

3. Implement `SemanticSolver` (Strategy 3)
   - Classify sub-goals semantically
   - Generate deterministic action sequences

4. Compare metrics across all three strategies
   - See which performs best on the 36 requests
   - Analyze tradeoffs (accuracy vs. efficiency)

## Running a Specific Solver

To test a different solver, modify `run_evaluation.py`:

```python
# Use FullContextSolver instead of DummyRequestSolver
solver = FullContextSolver(env_manager, llm_client)

# Or pass strategy parameter (if implemented)
solver = RequestSolver(env_manager, llm_client, strategy="semantic")
```

Then run: `python run_evaluation.py`

