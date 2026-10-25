# Cross-check of the hand-worked Kaplan-Meier fixture (MT19) against R survival's survfit.
# Run by hand: Rscript tests/benchmarks/tools/check_km_hand_fixture.R   (stops with an error on a difference)
suppressMessages(library(survival))
dir <- "tests/fixtures/hand/tier_b/MT19-kaplan-meier-ten-times"
d <- read.csv(file.path(dir, "times.csv"))
v <- read.csv(file.path(dir, "values.csv"))
f <- summary(survfit(Surv(time, event) ~ 1, data = d, conf.type = "log-log"))
pick <- function(q) v$value[v$quantity == q][match(f$time, v$key[v$quantity == q])]
check <- function(label, mine, theirs, tol = 1e-9) {
  worst <- max(abs(mine - theirs))
  cat(sprintf("%-28s max abs difference %.3g\n", label, worst))
  if (worst > tol) stop(label)
}
check("survival", pick("survival"), f$surv)
check("greenwood standard error", pick("greenwood_standard_error"), f$std.err)
check("log-log lower 95", pick("log_log_lower_95"), f$lower)
check("log-log upper 95", pick("log_log_upper_95"), f$upper)
check("at risk", pick("at_risk"), f$n.risk)
cat("survival", as.character(packageVersion("survival")), "agrees with the fixture\n")
