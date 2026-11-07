// Run with:  flutter test
//
// The old counter test from `flutter create` was removed: this app has no counter, so it could not pass.
// The softcopy / AI behaviour of the backend is covered by the Python tests (python3 -m pytest backend_tests).

import 'package:flutter_test/flutter_test.dart';

import 'package:app_prototype/services/backend_service.dart';

void main() {
  test('BackendException shows its message to the operator unchanged', () {
    final e = BackendException('That USB stick is not connected any more.');
    expect(e.toString(), 'That USB stick is not connected any more.');
    expect(e.message, e.toString());
  });
}
