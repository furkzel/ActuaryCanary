# Cox proportional hazards reference values from R survival (MT19), written for freeze_survival.py.
# Usage: Rscript freeze_survival.R <output folder>
# Writes ovarian/ and lung/ sub folders with data.csv and values.csv; the manifests come from Python.
suppressMessages(library(survival))
out <- commandArgs(TRUE)[1]

num <- function(x) sprintf("%.17g", x)

freeze <- function(name, data, covars, tol) {
  dir <- file.path(out, name)
  dir.create(dir, recursive = TRUE, showWarnings = FALSE)
  write.csv(data, file.path(dir, "data.csv"), row.names = FALSE, quote = FALSE)
  rows <- list()
  add <- function(quantity, key, value, rel_tol, note) {
    rows[[length(rows) + 1]] <<- c(quantity, key, num(value), rel_tol, note)
  }
  formula <- as.formula(paste("Surv(time, event) ~", paste(covars, collapse = " + ")))
  add("data", "n", nrow(data), 0, "rows")
  add("data", "events", sum(data$event), 0, "rows with event = 1")
  add("data", "tied_event_times", sum(duplicated(data$time[data$event == 1])), 0,
      "event times shared with another event")
  for (ties in c("efron", "breslow")) {
    fit <- coxph(formula, data = data, ties = ties)
    s <- summary(fit)
    for (v in covars) {
      add(paste0(ties, "_coef"), v, unname(coef(fit)[v]), tol, "coxph coef")
      add(paste0(ties, "_se"), v, unname(s$coefficients[v, "se(coef)"]), tol, "coxph se(coef)")
      add(paste0(ties, "_z"), v, unname(s$coefficients[v, "z"]), tol, "Wald z")
    }
    add(paste0(ties, "_loglik"), "null", fit$loglik[1], tol, "partial log-likelihood at beta = 0")
    add(paste0(ties, "_loglik"), "fit", fit$loglik[2], tol, "partial log-likelihood at the estimate")
    add(paste0(ties, "_lr_test"), "statistic", unname(s$logtest["test"]), tol, "2 x (fit - null)")
    add(paste0(ties, "_wald_test"), "statistic", unname(s$waldtest["test"]), tol, "overall Wald")
  }
  df <- do.call(rbind, rows)
  colnames(df) <- c("quantity", "key", "value", "rel_tol", "note")
  write.csv(df, file.path(dir, "values.csv"), row.names = FALSE, quote = TRUE)
  writeLines(c(as.character(packageVersion("survival")), R.version.string),
             file.path(dir, "versions.txt"))
}

ov <- ovarian
freeze("ovarian", data.frame(time = ov$futime, event = ov$fustat, age = ov$age,
                             resid.ds = ov$resid.ds, rx = ov$rx, ecog.ps = ov$ecog.ps),
       c("age", "resid.ds", "rx", "ecog.ps"), 1e-5)

lg <- na.omit(lung[, c("time", "status", "age", "sex", "ph.ecog")])
freeze("lung", data.frame(time = lg$time, event = as.integer(lg$status == 2), age = lg$age,
                          sex = lg$sex, ph.ecog = lg$ph.ecog),
       c("age", "sex", "ph.ecog"), 1e-5)
