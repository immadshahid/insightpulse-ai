import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:insightpulse/core/api_client.dart';
import 'package:insightpulse/core/google_auth.dart';
import 'package:insightpulse/core/validation.dart';
import 'package:insightpulse/data/models.dart';
import 'package:mocktail/mocktail.dart';

import 'support.dart';

class FakeGoogle implements GoogleAuth {
  FakeGoogle({this.token, this.error});
  final String? token;
  final GoogleAuthException? error;
  int signOuts = 0;

  @override
  bool get available => true;

  @override
  Future<String?> signIn() async {
    if (error != null) throw error!;
    return token;
  }

  @override
  Future<void> signOut() async => signOuts++;
}

Future<void> openRegister(WidgetTester tester) async {
  await tester.tap(find.text('New here? Create an account'));
  await settle(tester);
}

void main() {
  group('rules match the server', () {
    test('email', () {
      expect(emailProblem(''), 'Enter your email');
      expect(emailProblem('ayesha@shop'), 'Enter a valid email address');
      expect(emailProblem('a b@shop.pk'), 'Enter a valid email address');
      expect(emailProblem('  ayesha@shop.pk '), isNull);
    });

    test('new password', () {
      expect(newPasswordProblem('abc1'), 'Use at least 8 characters');
      expect(newPasswordProblem('abcdefgh'), 'Use at least one letter and one number');
      expect(newPasswordProblem('12345678'), 'Use at least one letter and one number');
      expect(newPasswordProblem(' pass1234'), "Your password can't start or end with a space");
      expect(newPasswordProblem('${'é' * 37}1'), 'Use up to 64 characters');
      expect(newPasswordProblem('me1@shop.pk', email: 'ME1@shop.pk'), "Your password can't be the same as your email");
      expect(newPasswordProblem('blue-river-42'), isNull);
    });
  });

  testWidgets('sign-up explains weak passwords before calling the server', (tester) async {
    final api = defaultApi();
    await pumpApp(tester, api, loggedIn: false);
    await openRegister(tester);
    expect(find.text('At least 8 characters, with a letter and a number'), findsOneWidget);
    await tester.enterText(find.byType(TextFormField).at(0), 'ayesha@shop.pk');
    await tester.enterText(find.byType(TextFormField).at(1), 'password');
    await tester.tap(find.text('Create account'));
    await settle(tester);
    expect(find.text('Use at least one letter and one number'), findsOneWidget);
    verifyNever(() => api.register(any(), any()));
  });

  testWidgets('sign-up sends a good password and opens Home', (tester) async {
    final api = defaultApi();
    when(() => api.register(any(), any()))
        .thenAnswer((_) async => AuthResult(token: 'tok', email: 'ayesha.khan@example.com'));
    await pumpApp(tester, api, loggedIn: false);
    await openRegister(tester);
    await tester.enterText(find.byType(TextFormField).at(0), ' ayesha.khan@example.com ');
    await tester.enterText(find.byType(TextFormField).at(1), 'blue-river-42');
    await tester.tap(find.text('Create account'));
    await settle(tester);
    verify(() => api.register('ayesha.khan@example.com', 'blue-river-42')).called(1);
    expect(find.text('Ayesha'), findsOneWidget);
  });

  testWidgets('a taken email and a lockout show the server message', (tester) async {
    final api = defaultApi();
    when(() => api.register(any(), any()))
        .thenThrow(ApiException('An account with this email already exists. Try signing in.', status: 409));
    when(() => api.login(any(), any()))
        .thenThrow(ApiException('Too many attempts. Please wait 15 minutes and try again.', status: 429));
    await pumpApp(tester, api, loggedIn: false);
    await tester.enterText(find.byType(TextFormField).at(0), 'a@shop.pk');
    await tester.enterText(find.byType(TextFormField).at(1), 'whatever');
    await tester.tap(find.text('Sign in'));
    await settle(tester);
    expect(find.text('Too many attempts. Please wait 15 minutes and try again.'), findsOneWidget);
    await openRegister(tester);
    await tester.enterText(find.byType(TextFormField).at(0), 'a@shop.pk');
    await tester.enterText(find.byType(TextFormField).at(1), 'blue-river-42');
    await tester.tap(find.text('Create account'));
    await settle(tester);
    expect(find.text('An account with this email already exists. Try signing in.'), findsOneWidget);
  });

  testWidgets('without Firebase settings there is no Google button', (tester) async {
    await pumpApp(tester, defaultApi(), loggedIn: false);
    expect(find.text('Continue with Google'), findsNothing);
  });

  testWidgets('Continue with Google signs in with the Firebase token', (tester) async {
    final api = defaultApi();
    when(() => api.loginWithFirebase(any()))
        .thenAnswer((_) async => AuthResult(token: 'tok', email: 'ayesha.khan@example.com'));
    final google = FakeGoogle(token: 'firebase-id-token');
    await pumpApp(tester, api, loggedIn: false, google: google);
    await tester.tap(find.text('Continue with Google'));
    await settle(tester);
    verify(() => api.loginWithFirebase('firebase-id-token')).called(1);
    expect(find.text('Ayesha'), findsOneWidget);

    await tester.tap(find.byTooltip('Sign out'));
    await settle(tester);
    expect(google.signOuts, 1);
    expect(find.text('Welcome back'), findsOneWidget);
  });

  testWidgets('backing out of the Google chooser changes nothing', (tester) async {
    final api = defaultApi();
    await pumpApp(tester, api, loggedIn: false, google: FakeGoogle());
    await tester.tap(find.text('Continue with Google'));
    await settle(tester);
    verifyNever(() => api.loginWithFirebase(any()));
    expect(find.text('Welcome back'), findsOneWidget);
    expect(find.byIcon(Icons.error_outline), findsNothing);
  });

  testWidgets('Google problems are shown in plain words', (tester) async {
    final google = FakeGoogle(error: GoogleAuthException("Google sign-in isn't set up correctly for this app yet."));
    await pumpApp(tester, defaultApi(), loggedIn: false, google: google);
    await tester.tap(find.text('Continue with Google'));
    await settle(tester);
    expect(find.text("Google sign-in isn't set up correctly for this app yet."), findsOneWidget);
  });
  testWidgets('a new account with no data can still sign out', (tester) async {
    final api = defaultApi();
    when(() => api.datasets()).thenAnswer((_) async => const []);
    await pumpApp(tester, api);
    expect(find.text('Add your data'), findsOneWidget);
    await tester.tap(find.text('Data').last);
    await settle(tester);
    await tester.tap(find.byTooltip('Sign out'));
    await settle(tester);
    expect(find.text('Welcome back'), findsOneWidget);
  });
}
