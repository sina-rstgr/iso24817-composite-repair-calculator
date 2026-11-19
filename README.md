# ISO 24817 Composite Repair Calculator

A Python-based calculator for preliminary design calculations of Type A (non-through-wall) composite repairs on pipes and pipe fittings. The implementation follows the calculation approach documented in the source code and is intended as an educational and preliminary engineering tool related to ISO 24817:2017.

## Features

- Calculates the required composite repair thickness using the implemented design routes.
- Considers internal pressure and optional mechanical loads.
- Applies component factors for straight pipes, bends, tees, flanges, and reducers.
- Calculates repair overlap, taper, and total repair length.
- Performs the implemented lap-shear, interfacial-stress, and other applicable checks.
- Generates a readable text report or a JSON result.
- Accepts custom calculation cases through a JSON input file.

## Requirements

- Python 3.9 or newer
- No third-party Python packages are required; the calculator uses the Python standard library.

## Quick start

Run the included example from the project directory:

```bash
python run.py
```

The program uses `example_input.json` by default.

## Run a custom calculation

1. Make a copy of `example_input.json`.
2. Edit the input values for your case.
3. Run the calculator with your input file:

```bash
python run.py --input my_case.json
```

## Save the output

Save a text report:

```bash
python run.py --output report.txt
```

Export the result as JSON:

```bash
python run.py --format json --output result.json
```

You can combine the input and output options:

```bash
python run.py --input my_case.json --format json --output my_result.json
```

## Included example

`example_input.json` contains a demonstration case based on the worked-example parameters embedded in the original source script, identified there as ISO 24817:2017 Annex K, Example 1. The accompanying `example_report.txt` and `example_result.json` show the generated outputs for this example input.

This example demonstrates how the program is used. It is not an independent verification or certification of the implementation against the official standard.

## Project structure

```text
iso24817-composite-repair-calculator/
├── README.md
├── calculator.py
├── run.py
├── example_input.json
├── example_report.txt
└── example_result.json
```

## Scope and limitations

The current implementation does not calculate Type B (through-wall) defects, limited axial extent corrections, cyclic-load de-rating, environmental compatibility, or impact resistance. It does not cover every requirement or project-specific condition of ISO 24817.

**Engineering disclaimer:** This is an educational and preliminary calculation tool, not certified engineering software. It does not replace the official standard, a qualified defect assessment, project-specific design review, manufacturer data, or approval by a competent engineer. Verify all inputs, assumptions, equations, and results independently before using them in an actual repair design.

## Author

**Sina Rastegar**  

- [LinkedIn](https://www.linkedin.com/in/sina-rastegar/)
- [GitHub](https://github.com/sina-rstgr)
