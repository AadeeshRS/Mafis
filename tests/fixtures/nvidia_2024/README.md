# NVIDIA FY2024 source fixture

`annual_report.pdf` is an unmodified, born-digital publisher PDF, downloaded from
[NVIDIA's investor-relations CDN](https://s201.q4cdn.com/141608511/files/doc_financials/2024/ar/NVIDIA-2024-Annual-Report.pdf).
The archived filename is discoverable through NVIDIA's official investor search;
the current annual-report index also offers a different updated insert. Use the
exact URL and SHA-256 in `annotations.json`, not an interchangeable 2024 PDF.
The publisher's original copyright remains in the file; this is a research/test
source, not a MAFIS-authored report.

- Identity: NVIDIA Corporation (Nasdaq: NVDA), FY2024 annual-report package with
  annual review, proxy statement, and Form 10-K; fiscal year ended January 28, 2024.
- Size: 34,826,878 bytes; 187 PDF pages.
- SHA-256: `b0de35ded9da9463d5c33dce77cf9b2158b88cf666f144646d0cc64af23c5960`.
- Income statement: PDF page 150, printed page 50.
- Balance sheet: PDF page 152, printed page 52.
- Currency context: Foreign Currency Remeasurement, PDF page 157 / printed page 57.
- Monetary figures are USD millions. Income columns are years ended January 28,
  2024 and January 29, 2023; balance-sheet values are instants at January 28, 2024.

The six gold values are 60,922 and 26,974 revenue; 32,972 operating income;
29,760 net income; 44,345 current assets; and 10,631 current liabilities.
They and their row/date-column locations were checked visually on rendered
source pages. `annotations.json` is test ground truth only: neither the extractor
nor any production module loads it. No expected values or page indices are
hardcoded into the extractor.

Raw extraction asserts fiscal period ends; raw start dates stay null. Note 1
(PDF page 155 / printed page 55) explicitly states that FY2024, FY2023, and FY2022
were all 52-week years. Milestone 3 retains this policy and its source locator in
`SourceDocument`. The engine uses it to compute normalized annual intervals of
January 30, 2023–January 28, 2024 and January 31, 2022–January 29, 2023, retaining
the unchanged raw periods in each artifact. It never assumes January 1.

The extraction-to-calculation integration test registers the actual source and
six extracted claims, calculates all four approved operations, and checks the
stored artifacts against independent rational-number expectations. Expected
display values are revenue growth 125.8545%, operating margin 54.1217%, net margin
48.8493%, and current ratio 4.1713. Raw facts remain `single_source` / `pending`;
artifacts are `calculation_backed` / `pending`. No Financial Agent is executed.

The supported format profile is deliberately narrow: one complete income table
and one complete balance sheet, English date headers, explicit monetary scale,
numeric rows in date-column order, printed numeric footers, and an explicit
supported USD functional-currency context. Currency context is source-backed,
not inferred from `$` alone. OCR, split tables, alternate row aliases, other
currencies, source verification, and retrieval are not implemented.

Negative tests modify source-extracted lines or pass invalid document bytes to
exercise failures. They do not replace the real PDF in the six-value success
test. Rendered inspection images and temporary files stay in ignored `tmp/`.
