# Security

## Reporting

Please do not publish suspected vulnerabilities in a public issue. Use GitHub's private vulnerability reporting feature when it is available for this repository. If private reporting is unavailable, contact the repository owner through the contact information on the GitHub profile before disclosing details publicly.

Include the affected component, reproduction steps, expected impact and any relevant version or commit information.

## Scope

AtlasPay is a reference payment-system simulation and does not process real cardholder data or money. Security-sensitive areas still receive the same defensive treatment as application code, including authentication boundaries, input validation, database constraints, dependency updates and container runtime configuration.

The repository does not claim PCI DSS, scheme, ISO 27001 or other external certification.

## Supported version

Security fixes are applied to the current `main` branch. Older commits and development branches are not maintained as supported releases.
