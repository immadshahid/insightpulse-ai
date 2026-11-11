import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/brand.dart';
import '../core/format.dart';
import '../core/theme.dart';
import '../data/models.dart';
import '../state/providers.dart';
import '../widgets/common.dart';
import '../widgets/motion.dart';
import '../widgets/visuals.dart';

const _segmentColors = {
  'VIP': Color(0xFF4F46E5),
  'Loyal': Color(0xFF0891B2),
  'New': Color(0xFF0F7B4F),
  'Lapsed': Color(0xFFC2410C),
};

/// Who buys, who may be leaving, and how much money depends on them.
class CustomersScreen extends ConsumerWidget {
  const CustomersScreen({super.key, required this.datasetId, this.currency});

  final String datasetId;
  final String? currency;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final churn = ref.watch(churnProvider(datasetId));
    final segments = ref.watch(segmentsProvider(datasetId));
    return Scaffold(
      appBar: AppBar(title: const Text('Your customers')),
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: () async {
            ref.invalidate(churnProvider(datasetId));
            ref.invalidate(segmentsProvider(datasetId));
          },
          child: ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 32), children: [
            ...churn.when(
              loading: () => const [Skeleton(height: 170, radius: kRadius + 4)],
              error: (e, _) => [
                AppCard(child: InlineError('$e', onRetry: () => ref.invalidate(churnProvider(datasetId)))),
              ],
              data: (c) => [FadeSlideIn(child: _RiskHero(churn: c, currency: currency))],
            ),
            const SizedBox(height: 18),
            const SectionTitle('Customer groups'),
            ...segments.when(
              loading: () => const [SkeletonCard(chart: false)],
              error: (e, _) => [
                AppCard(child: InlineError('$e', onRetry: () => ref.invalidate(segmentsProvider(datasetId)))),
              ],
              data: (s) => [
                for (final (i, seg) in s.indexed)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: FadeSlideIn(index: i, child: _SegmentTile(segment: seg, currency: currency)),
                  ),
              ],
            ),
            ...churn.maybeWhen(
              orElse: () => const <Widget>[],
              data: (c) => [
                if (c.topAtRisk.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  const SectionTitle('Contact these first'),
                  AppCard(
                    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
                    child: Column(children: [
                      for (final (i, a) in c.topAtRisk.take(10).indexed) ...[
                        if (i > 0) const Divider(height: 1),
                        _AtRiskRow(customer: a, currency: currency),
                      ],
                    ]),
                  ),
                ],
              ],
            ),
          ]),
        ),
      ),
    );
  }
}

class _RiskHero extends StatelessWidget {
  const _RiskHero({required this.churn, this.currency});

  final ChurnReport churn;
  final String? currency;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final soft = Colors.white.withValues(alpha: 0.8);
    final high = churn.riskBands['high'] ?? 0;
    return GradientCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Yearly revenue at risk', style: t.labelLarge?.copyWith(color: soft, fontWeight: FontWeight.w600)),
        const SizedBox(height: 6),
        FittedBox(
          fit: BoxFit.scaleDown,
          alignment: Alignment.centerLeft,
          child: CountUpText(
            value: churn.revenueAtRisk,
            format: (v) => money(v, currency),
            finalText: money(churn.revenueAtRisk, currency),
            style: t.displaySmall?.copyWith(color: Colors.white, fontWeight: FontWeight.w800, letterSpacing: -1),
          ),
        ),
        const SizedBox(height: 8),
        Text('$high of ${churn.customersScored} customers are at high risk of not coming back.',
            style: t.bodyMedium?.copyWith(color: Colors.white, height: 1.4)),
      ]),
    );
  }
}

class _SegmentTile extends StatelessWidget {
  const _SegmentTile({required this.segment, this.currency});

  final CustomerSegment segment;
  final String? currency;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    final color = _segmentColors[segment.name] ?? Brand.indigo;
    final tint = Theme.of(context).brightness == Brightness.dark ? Color.lerp(color, Colors.white, 0.35)! : color;
    final share = segment.revenueShare > 1 ? segment.revenueShare / 100 : segment.revenueShare;
    return AppCard(
      padding: const EdgeInsets.all(14),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          IconBadge(icon: Icons.people_alt_outlined, color: tint, size: 32),
          const SizedBox(width: 10),
          Expanded(child: Text(segment.name, style: t.titleSmall?.copyWith(fontWeight: FontWeight.w700))),
          Text('${compactNumber(segment.customers)} customers', style: t.labelMedium?.copyWith(color: p.muted)),
        ]),
        const SizedBox(height: 10),
        ClipRRect(
          borderRadius: BorderRadius.circular(6),
          child: LinearProgressIndicator(
            value: share.clamp(0.0, 1.0),
            minHeight: 8,
            color: tint,
            backgroundColor: p.border,
            semanticsLabel: '${segment.name} share of revenue',
          ),
        ),
        const SizedBox(height: 8),
        Text(
          '${(share * 100).round()}% of revenue · spends about ${money(segment.avgSpend, currency)} · '
          'last bought ${segment.avgRecencyDays.round()} days ago on average',
          style: t.bodySmall?.copyWith(color: p.muted, height: 1.35),
        ),
      ]),
    );
  }
}

class _AtRiskRow extends StatelessWidget {
  const _AtRiskRow({required this.customer, this.currency});

  final AtRiskCustomer customer;
  final String? currency;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    final pct = (customer.probability * 100).round();
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 10),
      child: Row(children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(customer.customer, style: t.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
            const SizedBox(height: 2),
            Text('${customer.recencyDays} days since last order · ${money(customer.revenueLast365, currency)} last year',
                style: t.bodySmall?.copyWith(color: p.muted)),
          ]),
        ),
        const SizedBox(width: 8),
        Pill('$pct% risk', color: p.negative, background: p.negative.withValues(alpha: 0.12)),
      ]),
    );
  }
}
