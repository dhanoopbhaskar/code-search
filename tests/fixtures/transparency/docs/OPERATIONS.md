# Operations Runbook

## Deployment notes

Roll out new versions during the quiet window so rollbacks stay fast. Keep
the JWT signing key rotated per environment instead of reusing the development
value across stages.