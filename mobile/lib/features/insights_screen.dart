import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/brand.dart';
import '../core/share.dart';
import '../core/theme.dart';
import '../data/models.dart';
import '../state/providers.dart';
import '../widgets/common.dart';
import '../widgets/dataset_gate.dart';
import '../widgets/motion.dart';
import '../widgets/visuals.dart';

const _filters = [
  (null, 'All'),
  ('sales', 'Sales'),
  ('products', 'Products'),
  ('customers', 'Customers'),
  ('anomalies', 'Anomalies'),
];

const _generalFilters = [
  (null, 'All'),
  ('target', 'Outcome'),
  ('relationships', 'Relationships'),
  ('distributions', 'Distributions'),
  ('quality', 'Data quality'),
];

class InsightsScreen extends ConsumerStatefulWidget {
  const InsightsScreen({super.key});

  @override
  ConsumerState<InsightsScreen> createState() => _InsightsScreenState();
}

class _InsightsScreenState extends ConsumerState<InsightsScreen> {
  String? _category;

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          title: const Text('Insights'),
          actions: const [Padding(padding: EdgeInsets.only(right: 12), child: DatasetChip())],
        ),
        body: DatasetGate(builder: (context, dataset) {
          final filters = dataset.isGeneral ? _generalFilters : _filters;
          // A filter picked for another kind of dataset falls back to All.
          final category = filters.any((f) => f.$1 == _category) ? _category : null;
          final key = (datasetId: dataset.id, category: category);
          final feed = ref.watch(insightsProvider(key));
          return Column(children: [
            SizedBox(
              height: 56,
              child: ListView(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
                children: [
                  for (final (value, label) in filters)
                    Padding(
                      padding: const EdgeInsets.only(right: 8),
                      child: ChoiceChip(
                        label: Text(label),
                        selected: category == value,
                        showCheckmark: false,
                        onSelected: (_) {
                          HapticFeedback.selectionClick();
                          setState(() => _category = value);
                        },
                      ),
                    ),
                ],
              ),
            ),
            Expanded(
              child: RefreshIndicator(
                onRefresh: () async => ref.invalidate(insightsProvider(key)),
                child: feed.when(
                  skipLoadingOnReload: true,
                  loading: () => ListView(padding: const EdgeInsets.all(16), children: const [
                    SkeletonCard(),
                    SizedBox(height: 12),
                    SkeletonCard(),
                  ]),
                  error: (e, _) => ErrorState(error: e, onRetry: () => ref.invalidate(insightsProvider(key))),
                  data: (f) => f.items.isEmpty
                      ? ListView(children: const [
                          SizedBox(height: 60),
                          EmptyState(
                            icon: Icons.search_off_rounded,
                            title: 'Nothing here yet',
                            message: 'No insights in this category for your data. Try another filter.',
                          ),
                        ])
                      : ListView.separated(
                          padding: const EdgeInsets.fromLTRB(16, 4, 16, 32),
                          itemCount: f.items.length + 1 + (f.isPending ? 1 : 0),
                          separatorBuilder: (_, _) => const SizedBox(height: 12),
                          itemBuilder: (context, i) {
                            if (i == 0) return _FeedSummary(feed: f);
                            if (f.isPending && i == 1) return const _WritingBanner();
                            final index = i - 1 - (f.isPending ? 1 : 0);
                            return FadeSlideIn(index: index, child: InsightCard(insight: f.items[index]));
                          },
                        ),
                ),
              ),
            ),
          ]);
        }),
      );
}

/// "7 findings, 1 needs your attention".
class _FeedSummary extends StatelessWidget {
  const _FeedSummary({required this.feed});

  final InsightFeed feed;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    final n = feed.items.length;
    final alerts = feed.items.where((i) => i.isAnomaly).length;
    return Row(children: [
      Flexible(
        flex: 3,
        child: Text('$n finding${n == 1 ? '' : 's'}',
            maxLines: 1, overflow: TextOverflow.ellipsis, style: t.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
      ),
      if (alerts > 0) ...[
        const SizedBox(width: 8),
        Flexible(
          flex: 3,
          child: Pill('$alerts to check', icon: Icons.warning_amber_rounded, color: p.negative,
              background: p.negative.withValues(alpha: 0.12)),
        ),
      ],
      const SizedBox(width: 8),
      Expanded(
        flex: 4,
        child: Text('Most important first',
            textAlign: TextAlign.end,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: t.labelMedium?.copyWith(color: p.muted)),
      ),
    ]);
  }
}

class _WritingBanner extends StatelessWidget {
  const _WritingBanner();

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Row(children: [
      Icon(Icons.auto_awesome, size: 16, color: p.accent),
      const SizedBox(width: 6),
      Text('Writing plain-language explanations...',
          style: Theme.of(context).textTheme.bodySmall?.copyWith(color: p.muted)),
    ]);
  }
}

/// One insight: tag, headline, chart and a "Why it matters" line. Anomalies are orange.
class InsightCard extends ConsumerWidget {
  const InsightCard({super.key, required this.insight});

  final Insight insight;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    final anomaly = insight.isAnomaly;
    final b = Theme.of(context).brightness;
    final tint = Brand.tint(insight.category, b);
    return Card(
      color: anomaly ? p.warningSurface : null,
      clipBehavior: Clip.antiAlias,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(kRadius),
        side: BorderSide(color: anomaly ? p.negative.withValues(alpha: 0.5) : p.border),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        // Category accent stripe (anomalies get a warm gradient).
        Container(
          height: 4,
          decoration: BoxDecoration(
            gradient: LinearGradient(
              colors: anomaly
                  ? const [Color(0xFFF97316), Color(0xFFDB2777)]
                  : [tint, tint.withValues(alpha: 0.25)],
            ),
          ),
        ),
        Padding(
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 8),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            IconBadge(
              icon: Brand.categoryIcons[insight.category] ?? Icons.lightbulb_outline,
              color: anomaly ? p.negative : tint,
              size: 32,
            ),
            const SizedBox(width: 10),
            Flexible(
              child: Pill(
                insight.tag,
                color: anomaly ? p.negative : tint,
                background: (anomaly ? p.negative : tint).withValues(alpha: 0.12),
              ),
            ),
            const Spacer(),
            if (insight.narrative != null)
              Tooltip(message: 'Explained by AI', child: Icon(Icons.auto_awesome, size: 16, color: p.muted)),
          ]),
          const SizedBox(height: 10),
          Text(insight.headline, style: t.titleMedium?.copyWith(fontWeight: FontWeight.w700, height: 1.3)),
          if (insight.chartUrl != null) ...[
            const SizedBox(height: 12),
            ChartImage(insight.chartUrl!, title: insight.tag, semanticLabel: insight.headline),
          ],
          const SizedBox(height: 12),
          Text('Why it matters', style: t.labelLarge?.copyWith(color: p.muted, fontWeight: FontWeight.w700)),
          const SizedBox(height: 4),
          Text(insight.narrative ?? insight.whyItMatters, style: t.bodyMedium?.copyWith(height: 1.4)),
          const SizedBox(height: 4),
          Row(children: [
            IconButton(
              tooltip: 'Share insight',
              icon: Icon(Icons.ios_share_rounded, size: 20, color: p.muted),
              onPressed: () {
                HapticFeedback.selectionClick();
                ref.read(sharerProvider)(
                  withSignature('${insight.headline}\n\n${insight.narrative ?? insight.whyItMatters}'),
                  subject: insight.tag,
                );
              },
            ),
            Expanded(
              child: Align(
                alignment: Alignment.centerRight,
                child: TextButton.icon(
                onPressed: () {
                  HapticFeedback.selectionClick();
                  ref.read(chatDraftProvider.notifier).set('Tell me more about this: ${insight.headline}');
                  context.go('/ask');
                },
                icon: const Icon(Icons.auto_awesome, size: 18),
                label: const Text('Ask AI about this', overflow: TextOverflow.ellipsis),
              ),
              ),
            ),
          ]),
        ]),
      ),
      ]),
    );
  }
}
