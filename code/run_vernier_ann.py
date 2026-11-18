"""VSCode Run: static LHS270 + final30, fixed budget300, no failure refill."""
import vernier_campaign as campaign

TOTAL_EVALUATIONS=300


def settings():return dict(campaign.settings('static'),evaluations=TOTAL_EVALUATIONS)


def main(c=None,evaluate_batch=None):return campaign.main(settings() if c is None else c,evaluate_batch)


if __name__=='__main__':
    try:campaign.cli('static',settings())
    except KeyboardInterrupt:print('Stopped. Run the same file to resume; no failed point is replaced.')
