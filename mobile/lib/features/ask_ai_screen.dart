import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/brand.dart';
import '../core/share.dart';
import '../core/theme.dart';
import '../data/models.dart';
import '../state/providers.dart';
import '../widgets/common.dart';
import '../widgets/dataset_gate.dart';
import '../widgets/visuals.dart';

const _starters = [
  'Which products sold the most last month?',
  'How did revenue change over the last 30 days?',
  'Which city brings in the most revenue?',
  'What is my busiest weekday?',
];

const _generalStarters = [
  'Summarise this dataset in plain words',
  'Which groups differ the most in the outcome?',
  'Which numeric columns are most related?',
  'Are there missing values I should worry about?',
];

class AskAiScreen extends ConsumerStatefulWidget {
  const AskAiScreen({super.key});

  @override
  ConsumerState<AskAiScreen> createState() => _AskAiScreenState();
}

class _AskAiScreenState extends ConsumerState<AskAiScreen> {
  final _input = TextEditingController();
  final _scroll = ScrollController();
  final _focus = FocusNode();

  @override
  void initState() {
    super.initState();
    // A question handed over from another screen before this one was built.
    WidgetsBinding.instance.addPostFrameCallback((_) => _takeDraft(ref.read(chatDraftProvider)));
  }

  @override
  void dispose() {
    _input.dispose();
    _scroll.dispose();
    _focus.dispose();
    super.dispose();
  }

  /// Put a handed-over question in the input box so the user can edit and send it.
  void _takeDraft(String? draft) {
    if (draft == null || !mounted) return;
    _input.text = draft;
    _input.selection = TextSelection.collapsed(offset: draft.length);
    _focus.requestFocus();
    ref.read(chatDraftProvider.notifier).set(null);
  }

  void _send([String? text]) {
    final message = (text ?? _input.text).trim();
    if (message.isEmpty) return;
    HapticFeedback.lightImpact();
    _input.clear();
    ref.read(chatProvider.notifier).send(message);
  }

  void _scrollToEnd() => WidgetsBinding.instance.addPostFrameCallback((_) {
        if (_scroll.hasClients) {
          _scroll.animateTo(_scroll.position.maxScrollExtent,
              duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
        }
      });

  @override
  Widget build(BuildContext context) {
    ref.listen(chatProvider, (_, _) => _scrollToEnd());
    ref.listen(chatDraftProvider, (_, next) => _takeDraft(next));
    final entries = ref.watch(chatProvider);
    final busy = entries.isNotEmpty && entries.last.pending;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Ask AI'),
        actions: [
          if (entries.isNotEmpty)
            IconButton(
              tooltip: 'New chat',
              icon: const Icon(Icons.refresh_rounded),
              onPressed: () => ref.read(chatProvider.notifier).clear(),
            ),
          const Padding(padding: EdgeInsets.only(right: 12), child: DatasetChip()),
        ],
      ),
      body: DatasetGate(builder: (context, dataset) {
        return Column(children: [
          Expanded(
            child: entries.isEmpty
                ? _Intro(onPick: _send, general: dataset.isGeneral)
                : ListView.builder(
                    controller: _scroll,
                    padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
                    itemCount: entries.length,
                    itemBuilder: (context, i) {
                      final e = entries[i];
                      final isLast = i == entries.length - 1;
                      if (e.fromUser) return _UserBubble(text: e.text);
                      if (e.pending) return const _TypingBubble();
                      if (e.error != null) return _ErrorBubble(text: e.error!);
                      return _AiBubble(entry: e, showFollowUps: isLast && !busy, onFollowUp: _send);
                    },
                  ),
          ),
          _InputBar(controller: _input, focusNode: _focus, busy: busy, onSend: _send),
        ]);
      }),
    );
  }
}

class _Intro extends StatelessWidget {
  const _Intro({required this.onPick, this.general = false});

  final void Function(String) onPick;
  final bool general;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    return ListView(padding: const EdgeInsets.all(24), children: [
      const SizedBox(height: 12),
      Center(
        child: DecoratedBox(
          decoration: BoxDecoration(shape: BoxShape.circle, boxShadow: [
            BoxShadow(color: Brand.violet.withValues(alpha: 0.35), blurRadius: 28, offset: const Offset(0, 10)),
          ]),
          child: const AiAvatar(size: 72),
        ),
      ),
      const SizedBox(height: 16),
      Text(general ? 'Ask about your data' : 'Ask about your sales', textAlign: TextAlign.center,
          style: t.titleLarge?.copyWith(fontWeight: FontWeight.w800)),
      const SizedBox(height: 6),
      Text('Answers are calculated from your data, with a chart and a note on how they were worked out.',
          textAlign: TextAlign.center, style: t.bodyMedium?.copyWith(color: p.muted)),
      const SizedBox(height: 24),
      for (final q in general ? _generalStarters : _starters)
        Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: OutlinedButton(
            style: OutlinedButton.styleFrom(alignment: Alignment.centerLeft, padding: const EdgeInsets.all(14)),
            onPressed: () => onPick(q),
            child: Row(children: [
              Icon(Icons.chat_bubble_outline_rounded, size: 18, color: p.accent),
              const SizedBox(width: 10),
              Expanded(child: Text(q, style: TextStyle(color: p.text))),
              Icon(Icons.north_east_rounded, size: 18, color: p.muted),
            ]),
          ),
        ),
    ]);
  }
}

class _UserBubble extends StatelessWidget {
  const _UserBubble({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerRight,
      child: Container(
        margin: const EdgeInsets.only(bottom: 12, left: 48),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        decoration: BoxDecoration(
          gradient: Brand.hero(Theme.of(context).brightness),
          borderRadius: const BorderRadius.only(
            topLeft: Radius.circular(18),
            topRight: Radius.circular(18),
            bottomLeft: Radius.circular(18),
            bottomRight: Radius.circular(4),
          ),
        ),
        child: Text(text, style: const TextStyle(color: Colors.white, height: 1.35)),
      ),
    );
  }
}

/// Gradient avatar to the left of an assistant message.
class _WithAvatar extends StatelessWidget {
  const _WithAvatar({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 12, right: 16),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Padding(padding: EdgeInsets.only(top: 4), child: AiAvatar(size: 30)),
          const SizedBox(width: 8),
          Flexible(child: child),
        ]),
      );
}

class _AiBubble extends ConsumerWidget {
  const _AiBubble({required this.entry, required this.showFollowUps, required this.onFollowUp});

  final ChatEntry entry;
  final bool showFollowUps;
  final void Function(String) onFollowUp;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    final reply = entry.reply!;
    return _WithAvatar(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        AppCard(
          padding: const EdgeInsets.all(14),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            SelectableText(reply.answer, style: t.bodyLarge?.copyWith(height: 1.4)),
            if (reply.chartUrl != null) ...[
              const SizedBox(height: 12),
              ChartImage(reply.chartUrl!, title: 'Answer chart', semanticLabel: 'Chart for this answer'),
            ],
            if (reply.source == 'offline') ...[
              const SizedBox(height: 10),
              Pill('Quick answer', icon: Icons.bolt_rounded, color: p.muted, background: p.border),
            ],
            if (reply.steps.isNotEmpty) ...[
              const SizedBox(height: 10),
              _AgentsUsed(steps: reply.steps),
            ],
            if (reply.how != null) ...[
              const SizedBox(height: 10),
              Theme(
                data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
                child: ExpansionTile(
                  tilePadding: EdgeInsets.zero,
                  childrenPadding: const EdgeInsets.only(bottom: 4),
                  minTileHeight: kMinTouch,
                  leading: Icon(Icons.functions_rounded, size: 18, color: p.muted),
                  title: Text('How I got this', style: t.labelLarge?.copyWith(color: p.muted)),
                  children: [
                    if (reply.steps.isEmpty)
                      Align(
                        alignment: Alignment.centerLeft,
                        child: Text(reply.how!, style: t.bodySmall?.copyWith(color: p.muted)),
                      )
                    else ...[
                      for (final s in reply.steps) _StepRow(step: s),
                      if (reply.sources.isNotEmpty)
                        Padding(
                          padding: const EdgeInsets.only(top: 6),
                          child: Align(
                            alignment: Alignment.centerLeft,
                            child: Text('Sources: ${reply.sources.join(', ')}',
                                style: t.bodySmall?.copyWith(color: p.muted)),
                          ),
                        ),
                    ],
                  ],
                ),
              ),
            ],
          ]),
        ),
        Wrap(children: [
          TextButton.icon(
            style: TextButton.styleFrom(foregroundColor: p.muted, visualDensity: VisualDensity.compact),
            onPressed: () async {
              await Clipboard.setData(ClipboardData(text: reply.answer));
              HapticFeedback.selectionClick();
              if (context.mounted) {
                ScaffoldMessenger.of(context)
                  ..hideCurrentSnackBar()
                  ..showSnackBar(const SnackBar(content: Text('Answer copied')));
              }
            },
            icon: const Icon(Icons.copy_rounded, size: 16),
            label: const Text('Copy'),
          ),
          TextButton.icon(
            style: TextButton.styleFrom(foregroundColor: p.muted, visualDensity: VisualDensity.compact),
            onPressed: () {
              HapticFeedback.selectionClick();
              ref.read(sharerProvider)(withSignature(reply.answer), subject: 'InsightPulse answer');
            },
            icon: const Icon(Icons.ios_share_rounded, size: 16),
            label: const Text('Share'),
          ),
        ]),
        if (showFollowUps && reply.followUps.isNotEmpty) ...[
          const SizedBox(height: 10),
          Wrap(spacing: 8, runSpacing: 8, children: [
            for (final q in reply.followUps)
              ActionChip(
                label: Text(q),
                avatar: Icon(Icons.subdirectory_arrow_right_rounded, size: 16, color: p.accent),
                onPressed: () => onFollowUp(q),
              ),
          ]),
        ],
      ]),
    );
  }
}

const _agentLook = {
  'knowledge': (Icons.menu_book_outlined, 'Saved findings', Color(0xFF7C3AED)),
  'sql': (Icons.storage_rounded, 'SQL agent', Color(0xFF4F46E5)),
  'csv': (Icons.table_chart_outlined, 'CSV agent', Color(0xFF0891B2)),
};

/// Which members of the agent team worked on this answer.
class _AgentsUsed extends StatelessWidget {
  const _AgentsUsed({required this.steps});

  final List<AgentStep> steps;

  @override
  Widget build(BuildContext context) {
    final used = {for (final s in steps) s.agent};
    return Wrap(spacing: 6, runSpacing: 6, children: [
      for (final a in used)
        if (_agentLook[a] case final look?)
          Pill(look.$2, icon: look.$1, color: look.$3, background: look.$3.withValues(alpha: 0.12)),
    ]);
  }
}

class _StepRow extends StatelessWidget {
  const _StepRow({required this.step});

  final AgentStep step;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    final look = _agentLook[step.agent];
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Icon(look?.$1 ?? Icons.bolt_rounded, size: 16, color: look?.$3 ?? p.muted),
        const SizedBox(width: 8),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(step.summary, style: t.bodySmall),
            if (step.detail.isNotEmpty)
              SelectableText(step.detail,
                  style: t.labelSmall?.copyWith(color: p.muted, fontFamily: 'monospace')),
          ]),
        ),
      ]),
    );
  }
}

class _TypingBubble extends StatelessWidget {
  const _TypingBubble();

  @override
  Widget build(BuildContext context) => const Align(
        alignment: Alignment.centerLeft,
        child: _WithAvatar(
          child: AppCard(
            padding: EdgeInsets.all(16),
            child: TypingDots(),
          ),
        ),
      );
}

class _ErrorBubble extends StatelessWidget {
  const _ErrorBubble({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.only(bottom: 12, right: 24),
      child: AppCard(
        color: p.warningSurface,
        padding: const EdgeInsets.all(14),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(Icons.error_outline, color: p.negative),
          const SizedBox(width: 10),
          Expanded(child: Text(text, style: const TextStyle(height: 1.35))),
        ]),
      ),
    );
  }
}

class _InputBar extends StatelessWidget {
  const _InputBar({required this.controller, required this.focusNode, required this.busy, required this.onSend});

  final TextEditingController controller;
  final FocusNode focusNode;
  final bool busy;
  final void Function([String?]) onSend;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Material(
      color: p.card,
      child: SafeArea(
        top: false,
        child: Container(
          decoration: BoxDecoration(border: Border(top: BorderSide(color: p.border))),
          padding: const EdgeInsets.fromLTRB(8, 8, 8, 8),
          child: Row(children: [
            Expanded(
              child: TextField(
                controller: controller,
                focusNode: focusNode,
                minLines: 1,
                maxLines: 4,
                maxLength: 500,
                textInputAction: TextInputAction.send,
                onSubmitted: (_) => onSend(),
                decoration: const InputDecoration(
                  hintText: 'Ask about your sales...',
                  counterText: '',
                  contentPadding: EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                ),
              ),
            ),
            const SizedBox(width: 6),
            ValueListenableBuilder<TextEditingValue>(
              valueListenable: controller,
              builder: (context, value, _) => IconButton.filled(
                tooltip: 'Send',
                constraints: const BoxConstraints(minWidth: kMinTouch, minHeight: kMinTouch),
                onPressed: busy || value.text.trim().isEmpty ? null : () => onSend(),
                icon: const Icon(Icons.arrow_upward_rounded),
              ),
            ),
          ]),
        ),
      ),
    );
  }
}
