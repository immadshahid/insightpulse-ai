import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/api_client.dart';
import '../core/brand.dart';
import '../core/config.dart';
import '../core/google_auth.dart';
import '../core/prefs.dart';
import '../core/validation.dart';
import '../core/theme.dart';
import '../state/providers.dart';

class LoginScreen extends StatelessWidget {
  const LoginScreen({super.key});

  @override
  Widget build(BuildContext context) => const _AuthForm(register: false);
}

class RegisterScreen extends StatelessWidget {
  const RegisterScreen({super.key});

  @override
  Widget build(BuildContext context) => const _AuthForm(register: true);
}

/// Asks for the server address and only accepts one that answers.
class _ServerDialog extends ConsumerStatefulWidget {
  const _ServerDialog({required this.initial});

  final String initial;

  @override
  ConsumerState<_ServerDialog> createState() => _ServerDialogState();
}

class _ServerDialogState extends ConsumerState<_ServerDialog> {
  late final _field = TextEditingController(text: widget.initial);
  bool _checking = false;
  String? _error;

  @override
  void dispose() {
    _field.dispose();
    super.dispose();
  }

  Future<void> _connect() async {
    final url = normalizeServerUrl(_field.text);
    if (url.isEmpty) return;
    setState(() {
      _checking = true;
      _error = null;
    });
    final ok = await ref.read(apiClientProvider).canReach(url);
    if (!mounted) return;
    if (ok) {
      Navigator.pop(context, url);
    } else {
      setState(() {
        _checking = false;
        _error = 'No server found there. Check that the server window is open and both devices share the same Wi-Fi.';
      });
    }
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('Server address'),
    content: TextField(
      controller: _field,
      keyboardType: TextInputType.url,
      autocorrect: false,
      decoration: InputDecoration(
        hintText: 'http://192.168.1.5:8000',
        helperText: 'Shown in the server window',
        errorText: _error,
        errorMaxLines: 3,
      ),
    ),
    actions: [
      TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
      FilledButton(onPressed: _checking ? null : _connect, child: Text(_checking ? 'Checking...' : 'Connect')),
    ],
  );
}

class _AuthForm extends ConsumerStatefulWidget {
  const _AuthForm({required this.register});

  final bool register;

  @override
  ConsumerState<_AuthForm> createState() => _AuthFormState();
}

class _AuthFormState extends ConsumerState<_AuthForm> {
  final _form = GlobalKey<FormState>();
  final _email = TextEditingController();
  final _password = TextEditingController();
  bool _busy = false;
  bool _obscure = true;
  String? _error;

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_form.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final auth = ref.read(authProvider.notifier);
      widget.register
          ? await auth.register(_email.text, _password.text)
          : await auth.login(_email.text, _password.text);
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _google() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(authProvider.notifier).loginWithGoogle();
    } on GoogleAuthException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _editServer() async {
    final saved = ref.read(prefsProvider).getString(PrefKeys.serverUrl) ?? AppConfig.apiBaseUrl;
    final url = await showDialog<String>(
      context: context,
      builder: (_) => _ServerDialog(initial: saved),
    );
    if (url == null || !mounted) return;
    await ref.read(prefsProvider).setString(PrefKeys.serverUrl, url);
    ref.read(apiClientProvider).useServer(url);
    if (mounted) {
      setState(() => _error = null);
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Connected to the server')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    final top = MediaQuery.paddingOf(context).top;
    return Scaffold(
      body: SingleChildScrollView(
        child: Column(
          children: [
            // Gradient hero with the brand mark.
            Container(
              width: double.infinity,
              padding: EdgeInsets.fromLTRB(24, top + 28, 24, 72),
              decoration: BoxDecoration(
                gradient: Brand.hero(Theme.of(context).brightness),
                borderRadius: const BorderRadius.vertical(bottom: Radius.circular(32)),
              ),
              child: Stack(
                clipBehavior: Clip.none,
                children: [
                  Positioned(
                    right: -50,
                    top: -40,
                    child: Container(
                      width: 170,
                      height: 170,
                      decoration: BoxDecoration(shape: BoxShape.circle, color: Colors.white.withValues(alpha: 0.08)),
                    ),
                  ),
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: Colors.white.withValues(alpha: 0.18),
                          borderRadius: BorderRadius.circular(16),
                          border: Border.all(color: Colors.white.withValues(alpha: 0.3)),
                        ),
                        child: const Icon(Icons.insights_rounded, color: Colors.white, size: 28),
                      ),
                      const SizedBox(height: 18),
                      Text(
                        'InsightPulse AI',
                        style: t.headlineSmall?.copyWith(color: Colors.white, fontWeight: FontWeight.w800),
                      ),
                      const SizedBox(height: 6),
                      Text(
                        'Your sales data, explained in plain words.',
                        style: t.bodyLarge?.copyWith(color: Colors.white.withValues(alpha: 0.85)),
                      ),
                    ],
                  ),
                ],
              ),
            ),
            Transform.translate(
              offset: const Offset(0, -44),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 440),
                  child: Container(
                    padding: const EdgeInsets.fromLTRB(20, 22, 20, 12),
                    decoration: BoxDecoration(
                      color: p.card,
                      borderRadius: BorderRadius.circular(kRadius + 6),
                      border: Border.all(color: p.border),
                      boxShadow: [
                        BoxShadow(
                          color: Brand.indigo.withValues(alpha: 0.1),
                          blurRadius: 30,
                          offset: const Offset(0, 12),
                        ),
                      ],
                    ),
                    child: Form(
                      key: _form,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Text(
                            widget.register ? 'Create your account' : 'Welcome back',
                            style: t.headlineSmall?.copyWith(fontWeight: FontWeight.w800),
                          ),
                          const SizedBox(height: 6),
                          Text(
                            widget.register
                                ? 'Upload your sales data and get answers in minutes.'
                                : 'Sign in to see how your business is doing.',
                            style: t.bodyMedium?.copyWith(color: p.muted),
                          ),
                          const SizedBox(height: 24),
                          TextFormField(
                            controller: _email,
                            keyboardType: TextInputType.emailAddress,
                            autofillHints: const [AutofillHints.email],
                            textInputAction: TextInputAction.next,
                            decoration: const InputDecoration(labelText: 'Email', prefixIcon: Icon(Icons.mail_outline)),
                            validator: emailProblem,
                          ),
                          const SizedBox(height: 14),
                          TextFormField(
                            controller: _password,
                            obscureText: _obscure,
                            autofillHints: [widget.register ? AutofillHints.newPassword : AutofillHints.password],
                            onFieldSubmitted: (_) => _submit(),
                            decoration: InputDecoration(
                              labelText: 'Password',
                              helperText: widget.register ? 'At least 8 characters, with a letter and a number' : null,
                              prefixIcon: const Icon(Icons.lock_outline),
                              suffixIcon: IconButton(
                                tooltip: _obscure ? 'Show password' : 'Hide password',
                                icon: Icon(_obscure ? Icons.visibility_outlined : Icons.visibility_off_outlined),
                                onPressed: () => setState(() => _obscure = !_obscure),
                              ),
                            ),
                            validator: (v) => widget.register
                                ? newPasswordProblem(v, email: _email.text)
                                : (v ?? '').isEmpty
                                ? 'Enter your password'
                                : null,
                          ),
                          if (_error != null) ...[
                            const SizedBox(height: 14),
                            Container(
                              padding: const EdgeInsets.all(12),
                              decoration: BoxDecoration(
                                color: p.warningSurface,
                                borderRadius: BorderRadius.circular(12),
                              ),
                              child: Row(
                                children: [
                                  Icon(Icons.error_outline, color: p.negative),
                                  const SizedBox(width: 10),
                                  Expanded(
                                    child: Text(_error!, style: TextStyle(color: p.text)),
                                  ),
                                ],
                              ),
                            ),
                          ],
                          const SizedBox(height: 22),
                          FilledButton(
                            onPressed: _busy ? null : _submit,
                            child: _busy
                                ? const SizedBox(
                                    height: 20,
                                    width: 20,
                                    child: CircularProgressIndicator(strokeWidth: 2.4),
                                  )
                                : Text(widget.register ? 'Create account' : 'Sign in'),
                          ),
                          if (ref.watch(googleAuthProvider).available) ...[
                            const SizedBox(height: 14),
                            Row(
                              children: [
                                Expanded(child: Divider(color: p.border)),
                                Padding(
                                  padding: const EdgeInsets.symmetric(horizontal: 12),
                                  child: Text('or', style: t.labelMedium?.copyWith(color: p.muted)),
                                ),
                                Expanded(child: Divider(color: p.border)),
                              ],
                            ),
                            const SizedBox(height: 14),
                            OutlinedButton.icon(
                              onPressed: _busy ? null : _google,
                              style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(kMinTouch + 4)),
                              icon: const Icon(Icons.account_circle_outlined),
                              label: const Text('Continue with Google'),
                            ),
                          ],
                          const SizedBox(height: 6),
                          TextButton(
                            onPressed: () => context.go(widget.register ? '/login' : '/register'),
                            child: Text(
                              widget.register ? 'Already have an account? Sign in' : 'New here? Create an account',
                            ),
                          ),
                          TextButton.icon(
                            onPressed: _editServer,
                            icon: const Icon(Icons.dns_outlined, size: 18),
                            label: const Text('Server address'),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(Icons.lock_outline_rounded, size: 14, color: p.muted),
                  const SizedBox(width: 6),
                  Flexible(
                    child: Text(
                      'Your data stays private to your account.',
                      textAlign: TextAlign.center,
                      style: t.labelMedium?.copyWith(color: p.muted),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
