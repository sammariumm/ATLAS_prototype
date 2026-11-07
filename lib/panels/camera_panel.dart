import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_mjpeg/flutter_mjpeg.dart';
import '../services/backend_service.dart';

/// Where the images of this scan come from. Chosen first, before anything is captured or imported.
enum _Source { softcopy, camera }

/// One of the four views of a bilateral exam: Left CC, Left MLO, Right CC, Right MLO.
class _ViewSlot {
  final String side; // 'Left' or 'Right'
  final String view; // 'CC' or 'MLO'
  String status = 'pending'; // 'pending', 'captured' or 'na' (not available)
  String imagePath = ''; // the PNG the AI uses
  String previewPath = ''; // small JPEG for the screen and the PDF

  _ViewSlot(this.side, this.view);

  bool get isResolved => status != 'pending';
  String get shortLabel => '${side == 'Left' ? 'L' : 'R'} $view';
  String get longLabel => '${side.toUpperCase()} · $view';
}

class CameraPanel extends StatefulWidget {
  final String currentScanId;

  /// Called after the AI has analysed the views. [scanData] always holds all four views in the order
  /// L-CC, L-MLO, R-CC, R-MLO, each with status 'captured' or 'na'.
  final void Function(
    List<Map<String, dynamic>> scanData,
    Map<String, String>? leftResult,
    Map<String, String>? rightResult,
    Map<String, String>? combinedResult,
    String note,
  ) onAnalysisComplete;
  final VoidCallback onReset;

  /// False while another tab is on screen: the live camera stream is switched off to save CPU.
  final bool isActive;

  /// MJPEG stream served by the Raspberry Pi. Adjust to your backend's URL.
  final String streamUrl;

  const CameraPanel({
    super.key,
    required this.currentScanId,
    required this.onAnalysisComplete,
    required this.onReset,
    this.isActive = true,
    this.streamUrl = 'http://localhost:5000/video_feed',
  });

  @override
  State<CameraPanel> createState() => _CameraPanelState();
}

class _CameraPanelState extends State<CameraPanel> {
  static const Color _navy = Color(0xFF0F172A);
  static const Color _teal = Color(0xFF0D9488);
  static const Color _slate = Color(0xFF334155);

  final List<_ViewSlot> _slots = [
    _ViewSlot('Left', 'CC'),
    _ViewSlot('Left', 'MLO'),
    _ViewSlot('Right', 'CC'),
    _ViewSlot('Right', 'MLO'),
  ];

  _Source? _source; // null = the source has not been chosen yet
  int _current = 0; // index of the view being worked on
  bool _busy = false;
  bool _analyzing = false;
  String _busyLabel = '';

  _ViewSlot get _slot => _slots[_current];
  int get _capturedCount => _slots.where((s) => s.status == 'captured').length;
  int get _resolvedCount => _slots.where((s) => s.isResolved).length;
  bool get _allResolved => _slots.every((s) => s.isResolved);

  void _toast(String text, Color color) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(text, style: const TextStyle(color: Colors.white)),
        backgroundColor: color,
        duration: const Duration(seconds: 5),
      ),
    );
  }

  /// Moves on to the next view that still needs an image (wrapping around). Call inside setState.
  void _goToNextPending() {
    for (int step = 1; step <= _slots.length; step++) {
      final int i = (_current + step) % _slots.length;
      if (!_slots[i].isResolved) {
        _current = i;
        return;
      }
    }
  }

  // ---------------------------------------------------------------- camera
  Future<void> _captureFromCamera() async {
    final _ViewSlot slot = _slot;
    setState(() {
      _busy = true;
      _busyLabel = 'Photographing ${slot.longLabel}…';
    });
    try {
      final result = await BackendService.captureFromCamera(
        scanId: widget.currentScanId,
        side: slot.side,
        view: slot.view,
      );
      if (!mounted) return;
      setState(() {
        slot.status = 'captured';
        slot.imagePath = result['image_path'].toString();
        slot.previewPath = (result['preview_path'] ?? '').toString();
        _goToNextPending();
      });
      final List warnings = (result['warnings'] as List?) ?? const [];
      if (warnings.isNotEmpty) {
        _toast(warnings.join('\n'), Colors.orange.shade800);
      }
    } catch (e) {
      _toast('$e', Colors.red);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  // -------------------------------------------------------------- softcopy
  Future<Map<String, dynamic>?> _loadInbox() async {
    try {
      return await BackendService.listSoftcopy();
    } catch (e) {
      _toast('$e', Colors.red);
      return null;
    }
  }

  Future<void> _importSoftcopy() async {
    final _ViewSlot slot = _slot;
    final Map<String, dynamic>? first = await _loadInbox();
    if (first == null || !mounted) return;
    Map<String, dynamic> listing = first;
    String? chosen;
    while (true) {
      chosen = await _chooseFile(listing, slot);
      if (chosen != _refreshFiles) break;
      // REFRESH: the operator may just have plugged the stick in
      final Map<String, dynamic>? again = await _loadInbox();
      if (!mounted) return;
      if (again != null) listing = again;
    }
    if (chosen == null || !mounted) return;

    setState(() {
      _busy = true;
      _busyLabel = 'Converting ${slot.longLabel}…';
    });
    try {
      final result = await BackendService.importSoftcopy(
        scanId: widget.currentScanId,
        side: slot.side,
        view: slot.view,
        sourcePath: chosen,
      );
      if (!mounted) return;
      setState(() {
        slot.status = 'captured';
        slot.imagePath = result['image_path'].toString();
        slot.previewPath = (result['preview_path'] ?? '').toString();
        _goToNextPending();
      });
      final String format = (result['source_format'] ?? '').toString().toUpperCase();
      _toast(
        result['converted'] == true ? '$format converted to PNG' : 'PNG kept as it is',
        _teal,
      );
      final List warnings = (result['warnings'] as List?) ?? const [];
      if (warnings.isNotEmpty) {
        _toast(warnings.join('\n'), Colors.orange.shade800);
      }
    } catch (e) {
      _toast('$e', Colors.red);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  static const String _refreshFiles = '__refresh_file_list__';

  Future<String?> _chooseFile(Map<String, dynamic> listing, _ViewSlot slot) {
    final List<Map<String, dynamic>> files = List<Map<String, dynamic>>.from(listing['files'] as List);
    final List volumes = (listing['volumes'] as List?) ?? const [];
    final String emptyText = volumes.isEmpty
        ? 'No USB stick found.\nPlug in the stick with the images, then press REFRESH.'
        : 'No image files found on the USB stick.\nCheck the stick, then press REFRESH.';
    return showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Select file for ${slot.longLabel}'),
        contentPadding: const EdgeInsets.fromLTRB(8, 12, 8, 0),
        content: SizedBox(
          width: double.maxFinite,
          height: 380,
          child: files.isEmpty
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Text(
                      emptyText,
                      textAlign: TextAlign.center,
                    ),
                  ),
                )
              : ListView.separated(
                  itemCount: files.length,
                  separatorBuilder: (context, index) => const Divider(height: 1),
                  itemBuilder: (context, i) {
                    final Map<String, dynamic> f = files[i];
                    final String source = (f['source'] ?? '').toString();
                    return ListTile(
                      dense: true,
                      leading: const Icon(Icons.insert_drive_file),
                      title: Text(
                        (f['display'] ?? f['path']).toString(),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                      subtitle: Text(
                        '${source.isEmpty ? '' : '$source · '}${_describeFormat(f['format'])} · ${_formatSize(f['size'])} · ${_formatTime(f['modified'])}',
                      ),
                      onTap: () => Navigator.of(ctx).pop(f['path'].toString()),
                    );
                  },
                ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(_refreshFiles),
            child: const Text('REFRESH'),
          ),
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: const Text('CANCEL'),
          ),
        ],
      ),
    );
  }

  String _describeFormat(dynamic format) {
    final String f = (format ?? '').toString();
    if (f.isEmpty || f == 'unknown') return 'file';
    return f.toUpperCase();
  }

  String _formatSize(dynamic bytes) {
    final int b = (bytes is num) ? bytes.toInt() : 0;
    if (b >= 1024 * 1024) return '${(b / (1024 * 1024)).toStringAsFixed(1)} MB';
    if (b >= 1024) return '${(b / 1024).toStringAsFixed(0)} KB';
    return '$b B';
  }

  String _formatTime(dynamic seconds) {
    if (seconds is! num) return '';
    final DateTime d = DateTime.fromMillisecondsSinceEpoch(seconds.toInt() * 1000);
    String two(int n) => n.toString().padLeft(2, '0');
    return '${d.year}-${two(d.month)}-${two(d.day)} ${two(d.hour)}:${two(d.minute)}';
  }

  // ------------------------------------------------------------- the flow
  /// Throwing away up to four photographs is hard to undo, so ask first.
  Future<void> _confirmReset() async {
    final bool? discard = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Discard this scan?'),
        content: Text('The $_resolvedCount view${_resolvedCount == 1 ? '' : 's'} set so far will be discarded and a new scan will start.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('KEEP'),
          ),
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('DISCARD', style: TextStyle(color: Colors.red)),
          ),
        ],
      ),
    );
    if (discard == true && mounted) widget.onReset();
  }

  void _markNotAvailable() {
    final _ViewSlot slot = _slot;
    setState(() {
      slot.status = 'na';
      slot.imagePath = '';
      slot.previewPath = '';
      _goToNextPending();
    });
  }

  Future<void> _analyze() async {
    final List<_ViewSlot> captured = _slots.where((s) => s.status == 'captured').toList();
    if (captured.isEmpty) return;
    setState(() {
      _busy = true;
      _analyzing = true;
      _busyLabel = 'Analyzing ${captured.length} view${captured.length == 1 ? '' : 's'}…';
    });
    try {
      final result = await BackendService.analyze(
        scanId: widget.currentScanId,
        views: captured
            .map((s) => {'side': s.side, 'view': s.view, 'image_path': s.imagePath})
            .toList(),
      );
      if (!mounted) return;
      final List<Map<String, dynamic>> scanData = _slots
          .map((s) => <String, dynamic>{
                'side': s.side,
                'view': s.view,
                'status': s.status,
                'image_path': s.imagePath,
                'preview_path': s.previewPath,
              })
          .toList();
      widget.onAnalysisComplete(
        scanData,
        result['left'] as Map<String, String>?,
        result['right'] as Map<String, String>?,
        result['combined'] as Map<String, String>?,
        result['note'] as String,
      );
    } catch (e) {
      _toast('$e', Colors.red);
    } finally {
      if (mounted) {
        setState(() {
          _busy = false;
          _analyzing = false;
        });
      }
    }
  }

  // ------------------------------------------------------------------- UI
  @override
  Widget build(BuildContext context) {
    return Stack(
      fit: StackFit.expand,
      children: [
        _source == null ? _buildSourcePicker() : _buildCaptureScreen(),
        if (_busy)
          Container(
            color: Colors.black54,
            child: Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const CircularProgressIndicator(color: Colors.white),
                  const SizedBox(height: 16),
                  Text(
                    _busyLabel,
                    style: const TextStyle(color: Colors.white, fontSize: 16),
                  ),
                ],
              ),
            ),
          ),
      ],
    );
  }

  /// Step 1: softcopy (digital file) or camera?
  Widget _buildSourcePicker() {
    return Container(
      color: _navy,
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Icon(Icons.add_photo_alternate, color: Colors.white70, size: 56),
          const SizedBox(height: 12),
          const Text(
            'SELECT IMAGE SOURCE',
            textAlign: TextAlign.center,
            style: TextStyle(color: Colors.white, fontSize: 22, fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 4),
          Text(
            'Scan ${widget.currentScanId}',
            textAlign: TextAlign.center,
            style: const TextStyle(color: Colors.white54, fontSize: 14),
          ),
          const SizedBox(height: 28),
          _sourceButton(
            icon: Icons.folder_open,
            title: 'SOFTCOPY',
            subtitle: 'Digital file (DICOM, PNG, JPEG, …) from a USB stick',
            onTap: () => setState(() => _source = _Source.softcopy),
          ),
          const SizedBox(height: 16),
          _sourceButton(
            icon: Icons.photo_camera,
            title: 'CAMERA',
            subtitle: 'Photograph the film on the lightbox',
            onTap: () => setState(() => _source = _Source.camera),
          ),
          if (_resolvedCount > 0) ...[
            const SizedBox(height: 20),
            Text(
              '$_resolvedCount of 4 views already set for this scan',
              textAlign: TextAlign.center,
              style: const TextStyle(color: Colors.white54, fontSize: 13),
            ),
          ],
        ],
      ),
    );
  }

  Widget _sourceButton({
    required IconData icon,
    required String title,
    required String subtitle,
    required VoidCallback onTap,
  }) {
    return ElevatedButton(
      style: ElevatedButton.styleFrom(
        backgroundColor: _slate,
        padding: const EdgeInsets.symmetric(vertical: 22, horizontal: 16),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      ),
      onPressed: onTap,
      child: Row(
        children: [
          Icon(icon, color: Colors.white, size: 40),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 20,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  subtitle,
                  style: const TextStyle(color: Colors.white70, fontSize: 13),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  /// Step 2: the four views, one after the other.
  Widget _buildCaptureScreen() {
    final bool isCamera = _source == _Source.camera;
    final _ViewSlot slot = _slot;
    final bool slotDone = slot.status == 'captured';

    return Column(
      children: [
        Expanded(flex: 6, child: _buildTopArea(isCamera, slot)),
        Expanded(
          flex: 5,
          child: Container(
            color: _navy,
            padding: const EdgeInsets.fromLTRB(12, 6, 12, 10),
            child: SingleChildScrollView(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          isCamera ? 'CAMERA' : 'SOFTCOPY',
                          style: const TextStyle(
                            color: Colors.white,
                            fontWeight: FontWeight.bold,
                            fontSize: 16,
                          ),
                        ),
                      ),
                      TextButton.icon(
                        onPressed: _busy ? null : () => setState(() => _source = null),
                        icon: const Icon(Icons.swap_horiz, color: Colors.white70, size: 18),
                        label: const Text(
                          'Change source',
                          style: TextStyle(color: Colors.white70, fontSize: 12),
                        ),
                      ),
                      if (_resolvedCount > 0)
                        TextButton.icon(
                          onPressed: _busy ? null : _confirmReset,
                          icon: const Icon(Icons.refresh, color: Colors.redAccent, size: 18),
                          label: const Text(
                            'Discard & restart',
                            style: TextStyle(color: Colors.redAccent, fontSize: 12),
                          ),
                        ),
                    ],
                  ),
                  Row(
                    children: [
                      for (int i = 0; i < _slots.length; i++) Expanded(child: _chip(i)),
                    ],
                  ),
                  const SizedBox(height: 10),
                  Text(
                    _allResolved
                        ? 'All four views are set. Analyze, or tap a view to redo it.'
                        : '${slot.longLabel}   (view ${_current + 1} of 4)',
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 16,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    isCamera
                        ? 'Put this film on the lightbox, then press CAPTURE. If this view does not exist, press NOT AVAILABLE.'
                        : 'Pick the file for this view from the USB stick. If this view does not exist, press NOT AVAILABLE.',
                    style: const TextStyle(color: Colors.white54, fontSize: 12),
                  ),
                  const SizedBox(height: 10),
                  Row(
                    children: [
                      Expanded(
                        flex: 3,
                        child: ElevatedButton.icon(
                          style: ElevatedButton.styleFrom(
                            backgroundColor: _teal,
                            padding: const EdgeInsets.symmetric(vertical: 16),
                          ),
                          onPressed: _busy
                              ? null
                              : (isCamera ? _captureFromCamera : _importSoftcopy),
                          icon: Icon(
                            isCamera ? Icons.camera : Icons.folder_open,
                            color: Colors.white,
                            size: 24,
                          ),
                          label: Text(
                            slotDone
                                ? (isCamera ? 'RETAKE' : 'REPLACE FILE')
                                : (isCamera ? 'CAPTURE' : 'SELECT FILE'),
                            style: const TextStyle(
                              color: Colors.white,
                              fontSize: 16,
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        flex: 2,
                        child: OutlinedButton(
                          style: OutlinedButton.styleFrom(
                            side: const BorderSide(color: Colors.white54),
                            padding: const EdgeInsets.symmetric(vertical: 16),
                          ),
                          onPressed: _busy ? null : _markNotAvailable,
                          child: const Text(
                            'NOT AVAILABLE',
                            textAlign: TextAlign.center,
                            style: TextStyle(
                              color: Colors.white,
                              fontSize: 13,
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                        ),
                      ),
                    ],
                  ),
                  if (_allResolved) ...[
                    const SizedBox(height: 8),
                    ElevatedButton.icon(
                      style: ElevatedButton.styleFrom(
                        backgroundColor: Colors.amber.shade700,
                        padding: const EdgeInsets.symmetric(vertical: 16),
                      ),
                      onPressed: (_busy || _capturedCount == 0) ? null : _analyze,
                      icon: const Icon(Icons.analytics, color: Colors.black, size: 24),
                      label: Text(
                        _capturedCount == 0
                            ? 'CAPTURE AT LEAST ONE VIEW'
                            : 'ANALYZE $_capturedCount VIEW${_capturedCount == 1 ? '' : 'S'}',
                        style: const TextStyle(
                          color: Colors.black,
                          fontSize: 16,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }

  /// Live camera stream (camera source) or the file that was imported for this view (softcopy source).
  Widget _buildTopArea(bool isCamera, _ViewSlot slot) {
    Widget content;
    if (isCamera) {
      if (widget.isActive && !_analyzing) {
        content = Mjpeg(
          isLive: true,
          stream: widget.streamUrl,
          fit: BoxFit.contain,
          error: (context, error, stack) => const Center(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.videocam_off, color: Colors.white54, size: 64),
                SizedBox(height: 16),
                Text(
                  'Camera stream unavailable',
                  style: TextStyle(color: Colors.white, fontSize: 16),
                ),
              ],
            ),
          ),
        );
      } else {
        content = const Center(
          child: Icon(Icons.videocam_off, color: Colors.white38, size: 56),
        );
      }
    } else if (slot.status == 'captured' && slot.previewPath.isNotEmpty) {
      content = Image.file(
        File(slot.previewPath),
        fit: BoxFit.contain,
        errorBuilder: (context, error, stack) => const Center(
          child: Icon(Icons.broken_image, color: Colors.white54, size: 56),
        ),
      );
    } else {
      content = Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.folder_open, color: Colors.white38, size: 64),
            const SizedBox(height: 12),
            Text(
              slot.status == 'na'
                  ? '${slot.longLabel}\nmarked as not available'
                  : 'Select the softcopy file for\n${slot.longLabel}',
              textAlign: TextAlign.center,
              style: const TextStyle(color: Colors.white70, fontSize: 16),
            ),
          ],
        ),
      );
    }

    return Stack(
      fit: StackFit.expand,
      children: [
        Container(color: Colors.black, child: content),
        Positioned(
          top: 12,
          left: 12,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            color: Colors.black54,
            child: Text(
              'Target: ${slot.longLabel}',
              style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold),
            ),
          ),
        ),
      ],
    );
  }

  /// One of the four progress chips; tap it to work on (or redo) that view.
  Widget _chip(int i) {
    final _ViewSlot s = _slots[i];
    final bool selected = i == _current;
    Color background;
    IconData icon;
    Color iconColor;
    String caption;
    switch (s.status) {
      case 'captured':
        background = const Color(0xFF14532D);
        icon = Icons.check_circle;
        iconColor = const Color(0xFF4ADE80);
        caption = 'done';
        break;
      case 'na':
        background = const Color(0xFF1E293B);
        icon = Icons.block;
        iconColor = Colors.white38;
        caption = 'N/A';
        break;
      default:
        background = _slate;
        icon = Icons.radio_button_unchecked;
        iconColor = Colors.white54;
        caption = 'to do';
        break;
    }
    // A captured view shows a small picture of what was captured / imported; the others show a status icon.
    final Widget marker = (s.status == 'captured' && s.previewPath.isNotEmpty)
        ? ClipRRect(
            borderRadius: BorderRadius.circular(6),
            child: Container(
              width: 48,
              height: 48,
              color: Colors.black,
              child: Image.file(
                File(s.previewPath),
                fit: BoxFit.contain,
                cacheWidth: 120,
                errorBuilder: (context, error, stack) => Icon(icon, color: iconColor, size: 22),
              ),
            ),
          )
        : SizedBox(height: 48, child: Center(child: Icon(icon, color: iconColor, size: 26)));
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 3),
      child: GestureDetector(
        onTap: _busy ? null : () => setState(() => _current = i),
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 8),
          decoration: BoxDecoration(
            color: background,
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: selected ? _teal : Colors.transparent, width: 2.5),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              marker,
              const SizedBox(height: 2),
              Text(
                s.shortLabel,
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 13,
                  fontWeight: FontWeight.bold,
                ),
              ),
              Text(caption, style: const TextStyle(color: Colors.white60, fontSize: 10)),
            ],
          ),
        ),
      ),
    );
  }
}
