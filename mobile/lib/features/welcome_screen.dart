import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/brand.dart';
import '../core/prefs.dart';
import '../state/providers.dart';

const _slides = [
  (
    Icons.upload_file_rounded,
    'Drop in your sales file',
    'Excel or CSV straight from your shop system. We tidy the columns and check the data for you.',
  ),
  (
    Icons.insights_rounded,
    'See what changed, and why',
    'Plain-language insights, a forecast you can trust, and the three things to do next.',
  ),
  (
    Icons.auto_awesome,
    'Ask in your own words',
    '"Which city sells the most?" Answers are calculated from your numbers, never guessed.',
  ),
];

/// First-launch tour (three slides). Shown once, before sign in.
class WelcomeScreen extends ConsumerStatefulWidget {
  const WelcomeScreen({super.key});

  @override
  ConsumerState<WelcomeScreen> createState() => _WelcomeScreenState();
}

class _WelcomeScreenState extends ConsumerState<WelcomeScreen> {
  final _pages = PageController();
  int _index = 0;

  @override
  void dispose() {
    _pages.dispose();
    super.dispose();
  }

  Future<void> _finish() async {
    HapticFeedback.lightImpact();
    await ref.read(prefsProvider).setString(PrefKeys.onboarded, '1');
    if (mounted) context.go('/login');
  }

  void _next() {
    if (_index == _slides.length - 1) {
      _finish();
      return;
    }
    HapticFeedback.selectionClick();
    final reduce = MediaQuery.maybeDisableAnimationsOf(context) ?? false;
    reduce
        ? _pages.jumpToPage(_index + 1)
        : _pages.nextPage(duration: const Duration(milliseconds: 350), curve: Curves.easeOutCubic);
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final last = _index == _slides.length - 1;
    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: SystemUiOverlayStyle.light,
      child: Scaffold(
        body: Container(
          decoration: BoxDecoration(gradient: Brand.hero(Theme.of(context).brightness)),
          child: SafeArea(
            child: Column(children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 8, 8, 0),
                child: Row(children: [
                  const Icon(Icons.insights_rounded, color: Colors.white),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text('InsightPulse AI',
                        style: t.titleMedium?.copyWith(color: Colors.white, fontWeight: FontWeight.w800)),
                  ),
                  if (!last)
                    TextButton(
                      style: TextButton.styleFrom(foregroundColor: Colors.white),
                      onPressed: _finish,
                      child: const Text('Skip'),
                    ),
                ]),
              ),
              Expanded(
                child: PageView.builder(
                  controller: _pages,
                  itemCount: _slides.length,
                  onPageChanged: (i) => setState(() => _index = i),
                  itemBuilder: (context, i) => _Slide(slide: _slides[i]),
                ),
              ),
              Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                for (var i = 0; i < _slides.length; i++)
                  AnimatedContainer(
                    duration: const Duration(milliseconds: 250),
                    margin: const EdgeInsets.symmetric(horizontal: 4),
                    width: i == _index ? 24 : 8,
                    height: 8,
                    decoration: BoxDecoration(
                      color: Colors.white.withValues(alpha: i == _index ? 1 : 0.4),
                      borderRadius: BorderRadius.circular(8),
                    ),
                  ),
              ]),
              Padding(
                padding: const EdgeInsets.fromLTRB(24, 24, 24, 20),
                child: SizedBox(
                  width: double.infinity,
                  child: FilledButton(
                    style: FilledButton.styleFrom(
                      backgroundColor: Colors.white,
                      foregroundColor: Brand.indigo,
                      minimumSize: const Size.fromHeight(54),
                    ),
                    onPressed: _next,
                    child: Text(last ? 'Get started' : 'Next'),
                  ),
                ),
              ),
            ]),
          ),
        ),
      ),
    );
  }
}

class _Slide extends StatelessWidget {
  const _Slide({required this.slide});

  final (IconData, String, String) slide;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final (icon, title, body) = slide;
    return LayoutBuilder(
      builder: (context, c) => SingleChildScrollView(
        padding: const EdgeInsets.symmetric(horizontal: 32),
        child: ConstrainedBox(
          constraints: BoxConstraints(minHeight: c.maxHeight),
          child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
            Container(
              width: 168,
              height: 168,
              decoration: BoxDecoration(shape: BoxShape.circle, color: Colors.white.withValues(alpha: 0.1)),
              alignment: Alignment.center,
              child: Container(
                width: 112,
                height: 112,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: Colors.white.withValues(alpha: 0.18),
                  border: Border.all(color: Colors.white.withValues(alpha: 0.35)),
                ),
                child: Icon(icon, size: 52, color: Colors.white),
              ),
            ),
            const SizedBox(height: 40),
            Text(title,
                textAlign: TextAlign.center,
                style: t.headlineSmall?.copyWith(color: Colors.white, fontWeight: FontWeight.w800)),
            const SizedBox(height: 12),
            Text(body,
                textAlign: TextAlign.center,
                style: t.bodyLarge?.copyWith(color: Colors.white.withValues(alpha: 0.85), height: 1.45)),
          ]),
        ),
      ),
    );
  }
}
