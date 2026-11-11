import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'package:flutter/services.dart';

import 'core/brand.dart';
import 'core/prefs.dart';
import 'core/theme.dart';
import 'features/ask_ai_screen.dart';
import 'features/auth_screens.dart';
import 'features/data_screen.dart';
import 'features/forecast_screen.dart';
import 'features/home_screen.dart';
import 'features/insights_screen.dart';
import 'features/welcome_screen.dart';
import 'state/providers.dart';

/// Re-runs the router's redirect whenever the auth state changes.
class _AuthListenable extends ChangeNotifier {
  void ping() => notifyListeners();
}

final routerProvider = Provider<GoRouter>((ref) {
  final refresh = _AuthListenable();
  ref.listen(authProvider, (_, _) => refresh.ping());
  ref.onDispose(refresh.dispose);

  return GoRouter(
    initialLocation: '/home',
    refreshListenable: refresh,
    redirect: (context, state) {
      final loggedIn = ref.read(authProvider) != null;
      final loc = state.matchedLocation;
      final onAuth = loc == '/login' || loc == '/register' || loc == '/welcome';
      if (!loggedIn) {
        final onboarded = ref.read(prefsProvider).getString(PrefKeys.onboarded) != null;
        if (!onboarded) return loc == '/welcome' ? null : '/welcome';
        if (loc == '/welcome') return '/login';
        return onAuth ? null : '/login';
      }
      if (onAuth) return '/home';
      return null;
    },
    routes: [
      GoRoute(path: '/welcome', builder: (_, _) => const WelcomeScreen()),
      GoRoute(path: '/login', builder: (_, _) => const LoginScreen()),
      GoRoute(path: '/register', builder: (_, _) => const RegisterScreen()),
      StatefulShellRoute.indexedStack(
        builder: (context, state, shell) => AppShell(shell: shell),
        branches: [
          StatefulShellBranch(routes: [GoRoute(path: '/home', builder: (_, _) => const HomeScreen())]),
          StatefulShellBranch(routes: [GoRoute(path: '/insights', builder: (_, _) => const InsightsScreen())]),
          StatefulShellBranch(routes: [GoRoute(path: '/forecast', builder: (_, _) => const ForecastScreen())]),
          StatefulShellBranch(routes: [GoRoute(path: '/ask', builder: (_, _) => const AskAiScreen())]),
          StatefulShellBranch(routes: [GoRoute(path: '/data', builder: (_, _) => const DataScreen())]),
        ],
      ),
    ],
  );
});

class InsightPulseApp extends ConsumerWidget {
  const InsightPulseApp({super.key, this.googleFonts = true});

  final bool googleFonts;

  @override
  Widget build(BuildContext context, WidgetRef ref) => MaterialApp.router(
        title: 'InsightPulse AI',
        debugShowCheckedModeBanner: false,
        theme: buildTheme(Brightness.light, googleFonts: googleFonts),
        darkTheme: buildTheme(Brightness.dark, googleFonts: googleFonts),
        themeMode: ref.watch(themeModeProvider),
        routerConfig: ref.watch(routerProvider),
      );
}

/// Bottom tab bar: Home, Insights, Forecast, Ask AI, Data.
class AppShell extends StatelessWidget {
  const AppShell({super.key, required this.shell});

  final StatefulNavigationShell shell;

  static const tabs = [
    (Icons.home_outlined, Icons.home_rounded, 'Home'),
    (Icons.lightbulb_outline, Icons.lightbulb_rounded, 'Insights'),
    (Icons.show_chart_outlined, Icons.show_chart_rounded, 'Forecast'),
    (Icons.chat_bubble_outline, Icons.chat_bubble_rounded, 'Ask AI'),
    (Icons.folder_open_outlined, Icons.folder_rounded, 'Data'),
  ];

  static const askIndex = 3;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final dark = Theme.of(context).brightness == Brightness.dark;
    return Scaffold(
      body: shell,
      // Floating rounded bar; the Ask AI tab wears the brand gradient.
      bottomNavigationBar: SafeArea(
        minimum: const EdgeInsets.fromLTRB(12, 0, 12, 10),
        child: Container(
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(26),
            border: Border.all(color: p.border),
            boxShadow: [
              BoxShadow(
                color: (dark ? Colors.black : Brand.indigo).withValues(alpha: dark ? 0.4 : 0.1),
                blurRadius: 24,
                offset: const Offset(0, 8),
              ),
            ],
          ),
          child: ClipRRect(
            borderRadius: BorderRadius.circular(26),
            child: MediaQuery.removePadding(
              context: context,
              // This context sits above the Scaffold, so it still carries the
              // status-bar and gesture-bar insets: drop both.
              removeTop: true,
              removeBottom: true,
              child: NavigationBar(
                selectedIndex: shell.currentIndex,
                onDestinationSelected: (i) {
                  HapticFeedback.selectionClick();
                  shell.goBranch(i, initialLocation: i == shell.currentIndex);
                },
                destinations: [
                  for (final (i, (icon, selected, label)) in tabs.indexed)
                    NavigationDestination(
                      icon: i == askIndex ? const _AskIcon(selected: false) : Icon(icon),
                      selectedIcon: i == askIndex ? const _AskIcon(selected: true) : Icon(selected),
                      label: label,
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// Gradient spark badge for the Ask AI tab.
class _AskIcon extends StatelessWidget {
  const _AskIcon({required this.selected});

  final bool selected;

  @override
  Widget build(BuildContext context) => Container(
        width: 30,
        height: 30,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          gradient: Brand.hero(Theme.of(context).brightness),
          boxShadow: selected
              ? [BoxShadow(color: Brand.violet.withValues(alpha: 0.45), blurRadius: 10, offset: const Offset(0, 3))]
              : null,
        ),
        child: const Icon(Icons.auto_awesome, size: 16, color: Colors.white),
      );
}
