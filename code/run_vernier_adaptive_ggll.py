"""VSCode Run: GGLL300 per TXT: DOE -> fit -> Pareto -> verify5.

Use --dry-run for a fully synthetic orchestration check without Ansys.
"""
import vernier_campaign as campaign

TOTAL_EVALUATIONS=300


def settings():return dict(campaign.settings('adaptive'),evaluations=TOTAL_EVALUATIONS)


def main(c=None,evaluate_batch=None):return campaign.main(settings() if c is None else c,evaluate_batch)


if __name__=='__main__':
    try:campaign.cli('adaptive',settings())
    except KeyboardInterrupt:print('Stopped. Run the same file to resume; no failed point is replaced.')
