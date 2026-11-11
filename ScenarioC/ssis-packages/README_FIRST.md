# Scenario A fixed package for Migration Forge v1.3

**Use `A_Employees_Active_Bonus_FIXED.dtsx` for the new Scenario A SCT deployment path.** Do not use the old package with destination under `fixtures\expected`. The new file is structurally checked, but actual SSDT/dtexec compatibility has NOT been verified in this environment. The application can run the controlled package on your Windows machine and compare its real output to the expected CSV.

For Scenario A: create a **new** session, upload FIXED, click Run SSIS & verify real output, Convert with AWS SCT, Prepare SCT-converted candidate, Validate local PySpark, then choose SCT-converted candidate at Deploy.

For B and C, the original native SSIS package candidates remain as provided in v1.2; their SCT candidate deployment is **blocked** and their independently authored reference Glue path remains separate.
